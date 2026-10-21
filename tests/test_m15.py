"""M15: 리뷰 비용 줄이기 — 리뷰 패킷, JSON 판정, 리뷰어 세션 재사용 (DESIGN.md 21장)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import tenure.orchestrator as orch_mod
from tenure.agents.base import AgentRequest, Mode
from tenure.agents.claude_code import ClaudeCodeAdapter
from tenure.agents.codex import CodexAdapter
from tenure.agents.mock import MockAdapter
from tenure.cli import main
from tenure.config import Config, ConfigError, load_config
from tenure.packet import call_sites, changed_symbols
from tenure.review_json import REVIEW_SCHEMA, output_instruction, render_review
from tenure.state import RunState, list_run_dirs
from tenure.transcript import Transcript
from tenure.usage import codex_resumed_usage
from tenure.verdict import parse_verdict
from tenure.workspace import Workspace
from tests.conftest import read_dump


# ====================================================================== 21.1 패킷
DIFF = """diff --git a/a.py b/a.py
@@ -1,3 +1,6 @@ class Store:
+def parse_line(text):
+    return text.strip()
+    def __init__(self):
+class Ledger:
@@ -20,2 +23,3 @@ def compute_total(items):
-    old
+    new
+function renderRow(x) {
+fn go() {}
+export async function loadAll() {
"""


def test_changed_symbols():
    assert changed_symbols(DIFF) == ["Store", "parse_line", "Ledger", "compute_total", "renderRow", "loadAll"]
    assert changed_symbols("+def ab():\n") == []          # 너무 짧은 이름은 잡음


def test_call_sites(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.ensure_repo()
    (tmp_path / "a.py").write_text("def parse_line(t):\n    return t\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from a import parse_line\nx = parse_line('1')\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("\n".join(f"parse_line({i})" for i in range(9)) + "\n", encoding="utf-8")
    (tmp_path / "DESIGN.md").write_text("parse_line 를 쓴다\n", encoding="utf-8")
    (tmp_path / ".tenure").mkdir()
    (tmp_path / ".tenure" / "x.py").write_text("parse_line()\n", encoding="utf-8")
    ws.commit_all("init")
    out = call_sites(ws, ["parse_line", "nothing_here"], exclude=("DESIGN.md",))
    lines = out.splitlines()
    assert lines[0] == "parse_line:" and len(lines) == 1 + 5          # 이름당 5줄
    assert "a.py:1" not in out and "DESIGN.md" not in out and ".tenure" not in out
    assert "b.py:1: from a import parse_line" in out
    assert call_sites(ws, ["nothing_here"]) == ""


# ====================================================================== 21.2 JSON 판정
def test_render_review_roundtrip_to_verdict():
    data = {"status": "CHANGES_REQUESTED", "summary": "요약",
            "findings": [{"severity": "P1", "new": True, "title": "[새] 빈 입력에서 죽음", "file": "a.py",
                          "detail": "IndexError", "evidence": "parse('')"},
                         {"severity": "P3", "new": False, "title": "이름", "file": "", "detail": "", "evidence": ""},
                         {"severity": "P2", "new": False, "title": "설계 위반", "file": "b.py", "detail": "x\ny", "evidence": ""}],
            "repro": [{"path": "tests/test_repro_empty.py", "content": "def test_x():\n    assert False\n"},
                      {"path": "", "content": "skip"}]}
    md = render_review(data)
    v = parse_verdict(md)
    assert v.status.value == "CHANGES_REQUESTED" and v.severity == {"P1": 1, "P2": 1, "P3": 1} and v.must_fix == 2
    must = md.split("## 반드시 고칠 것 (P1·P2)")[1].split("## 고치면 좋은 것")[0]
    assert "- [P1][새] 빈 입력에서 죽음 — `a.py`" in must and "근거: parse('')" in must and "설계 위반" in must
    assert '<repro path="tests/test_repro_empty.py">' in md and md.count("<repro") == 1
    ok = render_review({"status": "APPROVED", "summary": "", "findings": [], "repro": []})
    assert parse_verdict(ok).approved and "(없음)" in ok


@pytest.mark.parametrize("bad", [None, [], {"status": "MAYBE"}, {"status": "APPROVED", "findings": "x"},
                                 {"status": "APPROVED", "findings": [1]}])
def test_render_review_rejects_bad(bad):
    assert render_review(bad) is None


def test_schema_is_strict_compatible():
    def walk(node):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
            for v in node["properties"].values():
                walk(v)
        if node.get("type") == "array":
            walk(node["items"])
    walk(REVIEW_SCHEMA)


def test_output_instruction_modes():
    assert "<verdict>" in output_instruction(False, True, "RI") and "RI" in output_instruction(False, True, "RI")
    j = output_instruction(True, True, "RI")
    assert "JSON" in j and "<verdict>" not in j and "tests/test_repro_" in j
    assert "항상 빈 배열" in output_instruction(True, False, "")


# ====================================================================== 21.2·21.3 어댑터
def req(tmp_path, **kw) -> AgentRequest:
    return AgentRequest("리뷰해", tmp_path, Mode.READ, 20, "review", round=2, **kw)


def test_claude_flags(fake_cfg: Config, tmp_path: Path):
    a = ClaudeCodeAdapter(fake_cfg)
    cmd, _ = a.build_command(req(tmp_path, output_schema=REVIEW_SCHEMA, resume_session="sess-1"))
    i = cmd.index("--json-schema")
    assert json.loads(cmd[i + 1]) == REVIEW_SCHEMA
    assert cmd[cmd.index("--resume") + 1] == "sess-1"
    assert "Read,Glob,Grep" in cmd and cmd[-2:] == ["--", "리뷰해"]
    cmd, _ = a.build_command(req(tmp_path))
    assert "--json-schema" not in cmd and "--resume" not in cmd


def test_claude_structured_and_session(fake_cfg: Config, tmp_path: Path, monkeypatch):
    data = {"status": "APPROVED", "summary": "s", "findings": [], "repro": []}
    monkeypatch.setenv("TENURE_FAKE_STRUCTURED", json.dumps(data))
    monkeypatch.setenv("TENURE_FAKE_SESSION", "sess-abc")
    r = ClaudeCodeAdapter(fake_cfg).ask(req(tmp_path, output_schema=REVIEW_SCHEMA))
    assert r.ok and r.structured == data and r.session_id == "sess-abc" and not r.resumed
    monkeypatch.delenv("TENURE_FAKE_STRUCTURED")
    monkeypatch.setenv("TENURE_FAKE_TEXT", json.dumps(data))
    r = ClaudeCodeAdapter(fake_cfg).ask(req(tmp_path, output_schema=REVIEW_SCHEMA, resume_session="sess-abc"))
    assert r.structured == data and r.session_id == "sess-abc" and r.resumed


def test_claude_resume_failure_falls_back(fake_cfg: Config, tmp_path: Path, dump_path, monkeypatch):
    monkeypatch.setenv("TENURE_FAKE_SCENARIO", "fail_resume")
    monkeypatch.setenv("TENURE_FAKE_DUMP", str(dump_path))
    r = ClaudeCodeAdapter(fake_cfg).ask(req(tmp_path, resume_session="gone", fallback_prompt="전체 프롬프트"))
    assert r.ok and not r.resumed and r.session_id == "fake-session-new"
    argv = read_dump(dump_path)["argv"]
    assert "--resume" not in argv and argv[-1] == "전체 프롬프트"


def test_claude_no_fallback_on_rate_limit(fake_cfg: Config, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TENURE_FAKE_SCENARIO", "rate_limit")
    r = ClaudeCodeAdapter(fake_cfg).ask(req(tmp_path, resume_session="s", fallback_prompt="x"))
    assert r.rate_limited


def test_codex_resume_command(fake_cfg: Config, tmp_path: Path):
    a = CodexAdapter(fake_cfg)
    cmd, stdin = a.build_command(req(tmp_path, resume_session="sid-9"), tmp_path / "last.md", tmp_path / "s.json")
    assert cmd[1:4] == ["exec", "resume", "--skip-git-repo-check"]
    assert 'sandbox_mode="read-only"' in cmd and "--sandbox" not in cmd and "-C" not in cmd
    assert cmd[cmd.index("--output-schema") + 1] == str(tmp_path / "s.json")
    assert cmd[-3:] == ["--", "sid-9", "리뷰해"] and stdin is None
    # 쓰기 모드는 이어가지 않는다
    w = AgentRequest("x", tmp_path, Mode.WRITE, 20, "fix", resume_session="sid-9")
    cmd, _ = a.build_command(w, tmp_path / "last.md")
    assert "resume" not in cmd and "--sandbox" in cmd


def test_explicit_effort_overrides_step_effort(fake_cfg: Config, tmp_path: Path):
    cmd, _ = CodexAdapter(fake_cfg).build_command(req(tmp_path, resume_session="sid", effort="high"), tmp_path / "l.md")
    assert 'model_reasoning_effort="high"' in cmd                 # review 2라운드면 원래 rereview = medium
    cmd, _ = CodexAdapter(fake_cfg).build_command(req(tmp_path), tmp_path / "l.md")
    assert 'model_reasoning_effort="medium"' in cmd
    cfg = load_config(None, {"claude": {"bin": fake_cfg.claude.bin, "effort": "low"}}, global_defaults={})
    cmd, _ = ClaudeCodeAdapter(cfg).build_command(req(tmp_path, effort="max"))
    assert cmd[cmd.index("--effort") + 1] == "max"


def test_codex_resume_long_prompt_uses_stdin(tmp_path: Path, fake_bin: Path):
    cfg = load_config(None, {"codex": {"bin": str(fake_bin / "codex")}, "prompt_arg_max_bytes": 5}, global_defaults={})
    cmd, stdin = CodexAdapter(cfg).build_command(req(tmp_path, resume_session="sid"), tmp_path / "l.md")
    assert cmd[-3:] == ["--", "sid", "-"] and stdin == "리뷰해"


def test_codex_structured_session_and_resumed_usage(fake_cfg: Config, tmp_path: Path, monkeypatch):
    home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("TENURE_FAKE_CODEX_SESSION", "cx-1")
    data = {"status": "CHANGES_REQUESTED", "summary": "", "findings": [], "repro": []}
    monkeypatch.setenv("TENURE_FAKE_TEXT", json.dumps(data))
    a = CodexAdapter(fake_cfg)
    r = a.ask(req(tmp_path, output_schema=REVIEW_SCHEMA))
    assert r.ok and r.structured == data and r.session_id == "cx-1" and not r.resumed
    assert r.usage["input_tokens"] == 2000
    r2 = a.ask(req(tmp_path, output_schema=REVIEW_SCHEMA, resume_session="cx-1"))
    assert r2.resumed and r2.session_id == "cx-1"
    assert r2.usage["input_tokens"] == 600 and r2.usage["output_tokens"] == 50      # 누적값의 차이


def test_codex_resume_failure_falls_back(fake_cfg: Config, tmp_path: Path, dump_path, monkeypatch):
    monkeypatch.setenv("TENURE_FAKE_SCENARIO", "fail_resume")
    monkeypatch.setenv("TENURE_FAKE_DUMP", str(dump_path))
    r = CodexAdapter(fake_cfg).ask(req(tmp_path, resume_session="gone", fallback_prompt="전체"))
    assert r.ok and not r.resumed
    argv = read_dump(dump_path)["argv"]
    assert argv[:2] == ["exec", "--skip-git-repo-check"] and argv[-1] == "전체"


def test_codex_resumed_usage_delta(tmp_path: Path):
    import datetime as dt
    import time as _t

    folder = tmp_path / "sessions" / f"{dt.date.today():%Y/%m/%d}"
    folder.mkdir(parents=True)
    now = _t.time()

    def ts(offset):
        return dt.datetime.fromtimestamp(now + offset, dt.timezone.utc).isoformat().replace("+00:00", "Z")

    def tok(inp, out):
        return {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {
            "input_tokens": inp, "cached_input_tokens": inp // 2, "output_tokens": out, "reasoning_output_tokens": 0}}}}

    rows = [{"timestamp": ts(-100), "type": "session_meta", "payload": {"id": "S1", "cwd": "/x"}},
            {"timestamp": ts(-90), **tok(1000, 100)}, {"timestamp": ts(-80), **tok(3000, 300)},
            {"timestamp": ts(5), **tok(3500, 340)}, {"timestamp": ts(9), **tok(4200, 380)}]
    (folder / "rollout-x-S1.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    u = codex_resumed_usage("S1", now, home=tmp_path)
    assert u["input_tokens"] == 1200 and u["output_tokens"] == 80 and u["cached_input_tokens"] == 600
    assert codex_resumed_usage("NOPE", now, home=tmp_path) is None


# ====================================================================== 빌드 통합 (mock)
def run_mock(tmp_path: Path, monkeypatch, *extra: str, approve: int = 3, reuse: bool = False):
    seen: dict = {}
    if reuse:
        (tmp_path / "w").mkdir(exist_ok=True)
        (tmp_path / "w" / "tenure.toml").write_text('review_session = "reuse"\n', encoding="utf-8")

    def factory(cfg, *, mock):
        seen["claude"] = MockAdapter(label="claude")
        seen["codex"] = MockAdapter(label="codex", approve_on_review=approve)
        return dict(seen)

    monkeypatch.setattr(orch_mod, "make_agents", factory)
    wd = tmp_path / "w"
    rc = main(["run", "t", "--workdir", str(wd), "--mock", "--debate-rounds", "0", "--max-review", "4", *extra])
    [rd] = list_run_dirs(wd)
    return rc, seen, RunState.load(rd), rd


def reviews(seen):
    return [c for c in seen["codex"].calls if c.step == "review"]


def test_json_verdict_and_session_reuse(tmp_path: Path, monkeypatch):
    rc, seen, st, rd = run_mock(tmp_path, monkeypatch, approve=3, reuse=True)
    assert rc == 0
    rv = reviews(seen)
    assert [c.output_schema is REVIEW_SCHEMA or c.output_schema == REVIEW_SCHEMA for c in rv] == [True] * 3
    # codex 세션: 설계안 s1, 종합 s2, 첫 리뷰 s3 → 2·3라운드는 s3 을 이어감
    assert [c.resume_session for c in rv] == [None, "mock-codex-s3", "mock-codex-s3"]
    assert "이어서 해라" in rv[1].prompt and "지난 라운드에 '반드시 고칠 것'으로 지적한 것" in rv[1].prompt
    assert "예외 처리 없음" in rv[1].prompt                                     # 지난 지적 목록
    assert "너는 깐깐하지만" in rv[0].prompt and "JSON" in rv[0].prompt
    assert rv[1].fallback_prompt and "너는 깐깐하지만" in rv[1].fallback_prompt
    assert st.review_sessions["codex"] == {"id": "mock-codex-s3", "round": 3, "rounds": 3, "effort": "high", "model": ""}
    # 이어간 리뷰는 세션을 연 첫 리뷰의 강도(high)를 그대로 — rereview 강도(medium)로 바꾸면 Codex 캐시가 깨진다
    assert [c.effort for c in rv] == [None, "high", "high"]
    entries = {e.name: e for e in Transcript(rd).entries()}
    r1 = next(e for n, e in entries.items() if n.endswith("review1_codex.md"))
    r2 = next(e for n, e in entries.items() if n.endswith("review2_codex.md"))
    assert r1.meta["structured"] == "true" and "resumed" not in r1.meta and r2.meta["resumed"] == "true"
    body = r1.body()
    assert "## 반드시 고칠 것 (P1·P2)" in body and "<verdict>" in body and "p2: 1" in body
    assert st.review_history[0]["severity"] == {"P1": 0, "P2": 1, "P3": 0} and st.review_history[-1]["approved"]
    fix = [c for c in seen["claude"].calls if c.step == "fix"][0]
    assert "예외 처리 없음" in fix.prompt                                       # 렌더한 리뷰가 수정 프롬프트로


def test_session_rounds_cap(tmp_path: Path, monkeypatch):
    _, seen, st, _ = run_mock(tmp_path, monkeypatch, "--stall-rounds", "0", approve=4, reuse=True)
    # 한 세션은 최대 3라운드 → 4라운드는 새 세션(s4)
    assert [c.resume_session for c in reviews(seen)] == [None, "mock-codex-s3", "mock-codex-s3", None]
    assert st.review_sessions["codex"] == {"id": "mock-codex-s4", "round": 4, "rounds": 1, "effort": "medium", "model": ""}


def test_fresh_and_text_mode_via_toml(tmp_path: Path, monkeypatch):
    wd = tmp_path / "w"
    wd.mkdir()
    (wd / "tenure.toml").write_text('review_session = "fresh"\nreview_json = false\nreview_packet = false\n',
                                  encoding="utf-8")
    _, seen, st, rd = run_mock(tmp_path, monkeypatch, approve=2)
    rv = reviews(seen)
    assert [c.resume_session for c in rv] == [None, None] and all(c.output_schema is None for c in rv)
    assert "파일을 직접 열어봐도 된다" in rv[0].prompt and "<verdict>" in rv[0].prompt
    assert st.config["review_session"] == "fresh" and st.config["review_json"] is False
    assert st.review_sessions == {"codex": {"id": "mock-codex-s4", "round": 2, "rounds": 1, "effort": "medium", "model": ""}}


def test_packet_call_sites_in_prompt(tmp_path: Path, monkeypatch):
    seen: dict = {}

    def impl(req, n):
        if req.step == "implement":
            (Path(req.cwd) / "lib.py").write_text("def make_widget(x):\n    return x\n", encoding="utf-8")
            (Path(req.cwd) / "app.py").write_text("from lib import make_widget\nmake_widget(1)\n", encoding="utf-8")
            return "done"
        return MockAdapter(label="c")._default_response(req)

    def factory(cfg, *, mock):
        seen["claude"] = MockAdapter(label="claude", responder=impl)
        seen["codex"] = MockAdapter(label="codex", approve_on_review=1)
        return dict(seen)

    monkeypatch.setattr(orch_mod, "make_agents", factory)
    assert main(["run", "t", "--workdir", str(tmp_path / "w"), "--mock", "--debate-rounds", "0"]) == 0
    p = reviews(seen)[0].prompt
    sites = p.split("[바뀐 함수가 쓰이는 곳]")[1]
    assert "make_widget:" in sites and "app.py:2: make_widget(1)" in sites
    assert "diff 에 이미 있는 내용은 다시 열지 마라" in p


def test_multi_reviewers_each_resume_own_session(tmp_path: Path, monkeypatch):
    store: dict = {}

    def factory(cfg, wf, *, mock):
        agents = {n: MockAdapter(label=n, approve_on_review=2) for n in wf.used_roles()}
        store["a"] = agents
        return agents

    monkeypatch.setattr(orch_mod, "make_role_agents", factory)
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "tenure.toml").write_text('review_session = "reuse"\n', encoding="utf-8")
    assert main(["run", "t", "--workdir", str(tmp_path / "w"), "--mock", "--workflow", "secure",
                 "--debate-rounds", "0"]) == 0
    a = store["a"]
    assert [c.resume_session for c in a["codex"].calls if c.step == "review"] == [None, "mock-codex-s3"]
    assert [c.resume_session for c in a["security"].calls if c.step == "review"] == [None, "mock-security-s1"]
    sec2 = [c for c in a["security"].calls if c.step == "review"][1]
    assert "이어서 해라" in sec2.prompt


def test_default_is_fresh_sessions(tmp_path: Path, monkeypatch):
    _, seen, st, _ = run_mock(tmp_path, monkeypatch, approve=3)
    assert [c.resume_session for c in reviews(seen)] == [None, None, None]
    assert all(c.output_schema is not None for c in reviews(seen))          # JSON 판정은 기본으로 켜짐
    assert st.config["review_session"] == "fresh"


def test_custom_review_template_without_output_instruction_uses_text(tmp_path: Path, monkeypatch):
    wd = tmp_path / "w"
    (wd / ".tenure" / "templates").mkdir(parents=True)
    (wd / ".tenure" / "templates" / "review.md").write_text(
        "내 리뷰 {task}\n{diff}\n{repro_instruction}\n<verdict>\n", encoding="utf-8")
    _, seen, _, _ = run_mock(tmp_path, monkeypatch, approve=1)
    rv = reviews(seen)
    assert rv[0].output_schema is None and rv[0].prompt.startswith("내 리뷰")


@pytest.mark.parametrize("over", [{"review_session": "x"}, {"review_session_rounds": 0}, {"review_session_rounds": 11},
                                  {"review_json": "yes"}, {"review_packet": 1},
                                  {"codex": {"resume_args": "exec"}}])
def test_config_validation(over):
    with pytest.raises(ConfigError):
        load_config(None, over, global_defaults={})


def test_defaults():
    c = Config()
    assert (c.review_packet, c.review_json, c.review_session, c.review_session_rounds) == (True, True, "fresh", 3)
    assert c.codex.resume_args == ["exec", "resume", "--skip-git-repo-check"]
    assert c.codex.resume_read_args == ["-c", 'sandbox_mode="read-only"']
    assert c.claude.resume_args == [] and c.claude.resume_read_args == []
