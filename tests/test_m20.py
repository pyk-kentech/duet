"""M20: 재제기·되돌림 방지 (DESIGN.md 26장)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import tenure.orchestrator as orch_mod
from tenure import dedup, revert
from tenure.agents.base import AgentRequest, Mode
from tenure.agents.claude_code import ClaudeCodeAdapter
from tenure.agents.mock import MockAdapter
from tenure.cli import main
from tenure.config import Config, ConfigError, dedup_agent_config, load_config
from tenure.state import RunState, list_run_dirs
from tenure.transcript import Transcript, read_header
from tenure.workspace import Workspace


def item(i, status="open", sev="P2", round_=1, closed=None, note="", file="a.py", title=None):
    return {"id": i, "role": "codex", "round": round_, "severity": sev, "title": title or f"t{i}", "file": file,
            "status": status, "closed_round": closed, "note": note}


class S:
    def __init__(self, issues):
        self.issues = issues


# ====================================================================== 닫힌 지적 (26.1)
def test_closed_issues_and_block():
    st = S([item("I1", "resolved", closed=2), item("I2", "open"),
            item("I3", "rejected", closed=3, note="중재: 기각 — 근거가 틀림"),
            item("I4", "open", sev="P3", note="중재: 완화 — 요구 밖"), item("I5", "open", sev="P3", note="원래 P2: 근거 없음")])
    ids = [x["id"] for x in dedup.closed_issues(st)]
    assert set(ids) == {"I1", "I3", "I4"} and ids[0] == "I3"           # 최근에 닫힌 것부터
    text = dedup.format_closed(dedup.closed_issues(st))
    assert "- I1 [P2] tI1 — `a.py` (2라운드에 해결됨)" in text
    assert "(중재에서 기각됨: 근거가 틀림)" in text and "(중재에서 완화됨(P3): 요구 밖)" in text
    assert dedup.closed_block(st).startswith("[이미 닫힌 지적] 아래는 이미 해결됐거나")
    assert "되돌리지 마라" in dedup.closed_block(st, for_fix=True)
    assert dedup.closed_block(S([item("I1")])) == ""


def test_normalize_and_apply():
    closed = {x["id"]: x for x in [item("I1", "resolved", closed=2), item("I3", "rejected", note="중재: 기각 — 틀림"),
                                   item("I4", "open", sev="P3", note="중재: 완화 — 밖")]}
    data = {"matches": [{"new_id": "I7", "old_id": "I1", "reason": "같은 결함"},
                        {"new_id": "I8", "old_id": "I3", "reason": "같은 요구"},
                        {"new_id": "I9", "old_id": "I4", "reason": "같음"},
                        {"new_id": "I7", "old_id": "I3", "reason": "중복 매칭은 첫 것만"},
                        {"new_id": "I99", "old_id": "I1", "reason": "없는 새 ID"},
                        {"new_id": "I10", "old_id": "I42", "reason": "없는 옛 ID"}]}
    m = dedup.normalize(data, {"I7", "I8", "I9", "I10"}, set(closed))
    assert m == {"I7": {"old_id": "I1", "reason": "같은 결함"}, "I8": {"old_id": "I3", "reason": "같은 요구"},
                 "I9": {"old_id": "I4", "reason": "같음"}}
    assert dedup.normalize({"x": 1}, set(), set()) is None
    findings = [{"id": "I7", "severity": "P2"}, {"id": "I8", "severity": "P1"}, {"id": "I9", "severity": "P2"},
                {"id": "I10", "severity": "P2"}]
    counts = dedup.apply(findings, m, closed)
    assert counts == {"repeat": 2, "recurred": 1, "same": 0}
    by = {f["id"]: f for f in findings}
    assert by["I7"]["severity"] == "P2" and by["I7"]["note"] == "I1 재발(회귀 가능성)" and by["I7"]["repeat_of"] == "I1"
    assert by["I8"]["severity"] == "P3" and by["I8"]["note"] == "원래 P1: I3 재제기 — 중재에서 기각됨: 틀림"
    assert by["I9"]["severity"] == "P3" and "repeat_of" not in by["I10"]


def test_schema_strict_and_new_blocking():
    it = dedup.DEDUP_SCHEMA["properties"]["matches"]["items"]
    assert it["additionalProperties"] is False and set(it["required"]) == set(it["properties"])
    fs = [{"id": "I1", "new": True, "severity": "P2"}, {"id": "I2", "new": False, "severity": "P1"},
          {"id": "I3", "new": True, "severity": "P3"}]
    assert [f["id"] for f in dedup.new_blocking(fs)] == ["I1"]


def test_transcript_rewrite_keeps_header(tmp_path):
    t = Transcript(tmp_path)
    p = t.save("review1_codex", "옛 본문", {"agent": "codex", "step": "review"})
    t.rewrite(p.name, "새 본문", {"dedup": "재제기 1"})
    h = read_header(p)
    assert h["agent"] == "codex" and h["dedup"] == "재제기 1" and t.read(p.name).strip() == "새 본문"


# ====================================================================== 되돌림 감지 (26.3)
BUGGY = "def parse(s):\n    value = int(s)\n    result = value * 2\n    return result\n"
FIXED = "def parse(s):\n    if not s.strip():\n        raise ValueError('빈 입력')\n    value = int(s.strip())\n    result = value * 2\n    return result\n"


def git_repo(tmp_path):
    ws = Workspace(tmp_path / "r")
    ws.workdir.mkdir(parents=True)
    ws.ensure_repo()
    (ws.workdir / "DESIGN.md").write_text("# d\n", encoding="utf-8")
    return ws, ws.commit_all("base")


def commit(ws, text, msg):
    (ws.workdir / "a.py").write_text(text, encoding="utf-8")
    return ws.commit_all(msg)


def test_find_reverts_crossing_resolved_issue(tmp_path):
    ws, base = git_repo(tmp_path)
    c1 = commit(ws, BUGGY, "impl 1")           # 1라운드 리뷰 시점: 버그 있음 → I1
    c2 = commit(ws, FIXED, "impl 2")           # 2라운드 리뷰 시점: 고침 → I1 해결
    commit(ws, BUGGY + "# 다른 지적 때문에 바꿈\n", "impl 3")
    issues = [item("I1", "resolved", round_=1, closed=2)]
    [r] = revert.find_reverts(ws, c2, [(0, base), (1, c1)], issues)
    assert (r.file, r.point, r.issues, r.lines) == ("a.py", 1, ["I1"], 1)
    text = revert.format_reverts([r.to_dict()])
    assert "`a.py`: 1라운드 리뷰 시점의 코드" in text and "I1" in text


def test_find_reverts_quiet_without_crossed_issue(tmp_path):
    ws, base = git_repo(tmp_path)
    c1 = commit(ws, BUGGY, "impl 1")
    c2 = commit(ws, FIXED, "impl 2")
    commit(ws, BUGGY + "# x\n", "impl 3")
    assert revert.find_reverts(ws, c2, [(0, base), (1, c1)], []) == []
    other_file = [item("I1", "resolved", round_=1, closed=2, file="b.py")]
    assert revert.find_reverts(ws, c2, [(0, base), (1, c1)], other_file) == []
    later = [item("I1", "resolved", round_=2, closed=3)]          # 1라운드 코드에는 없던 결함
    assert revert.find_reverts(ws, c2, [(0, base), (1, c1)], later) == []


def test_find_reverts_ignores_new_code(tmp_path):
    ws, base = git_repo(tmp_path)
    c1 = commit(ws, BUGGY, "impl 1")
    c2 = commit(ws, FIXED, "impl 2")
    commit(ws, FIXED + "\ndef other(x):\n    total = x + 1\n    doubled = total * 2\n    return doubled\n", "impl 3")
    assert revert.find_reverts(ws, c2, [(0, base), (1, c1)], [item("I1", "resolved", round_=1, closed=2)]) == []


# ====================================================================== 설정·확인자 구성
def test_config_and_dedup_agent():
    c = Config()
    assert c.dedup is True and c.dedup_agent == "claude" and c.dedup_model == "claude-haiku-5-5"
    ac = dedup_agent_config(Config(claude=Config().claude))
    cmd = ClaudeCodeAdapter(c, ac).build_command(
        AgentRequest(prompt="p", cwd=Path("."), mode=Mode.READ, timeout_sec=60, step="dedup"))[0]
    assert cmd[cmd.index("--model") + 1] == "claude-haiku-5-5" and "--effort" not in cmd
    c2 = Config()
    c2.claude.effort = "high"
    assert dedup_agent_config(c2).effort == "" and c2.claude.effort == "high"     # 원래 설정은 그대로


def test_config_validation(tmp_path):
    (tmp_path / "tenure.toml").write_text('dedup_agent = "gemini"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="dedup_agent"):
        load_config(tmp_path, global_defaults={})
    (tmp_path / "tenure.toml").write_text('dedup_agent = "codex"\ndedup_model = "gpt-mini"\ndedup_effort = "low"\n',
                                        encoding="utf-8")
    c = load_config(tmp_path, global_defaults={})
    assert dedup_agent_config(c).model == "gpt-mini" and dedup_agent_config(c).effort == "low"


# ====================================================================== build 통합
def finding(fid="", sev="P2", title="빈 입력 처리 없음", file="main.py"):
    return {"id": fid, "severity": sev, "new": not fid, "title": title, "file": file, "detail": "빈 문자열에서 죽는다",
            "evidence": f"{file}:1 확인", "basis": "correctness", "requirement": ""}


def verdict(*fs):
    return {"status": "CHANGES_REQUESTED" if fs else "APPROVED", "summary": "", "findings": list(fs), "repro": []}


def scripted(reviews):
    st = {"n": 0}

    def responder(req, n):
        if req.step == "review":
            st["n"] += 1
            return json.dumps(reviews[min(st["n"], len(reviews)) - 1], ensure_ascii=False)
        return MockAdapter(label="codex")._default_response(req)
    return responder


def dedup_says(matches):
    return lambda req, n: json.dumps({"matches": matches}, ensure_ascii=False)


def run(tmp_path, monkeypatch, reviews, *extra, dedup_adapter=None, toml=""):
    seen: dict = {}

    def factory(cfg, *, mock):
        seen["claude"] = MockAdapter(label="claude")
        seen["codex"] = MockAdapter(label="codex", responder=scripted(reviews))
        if dedup_adapter is not None:
            seen["dedup"] = dedup_adapter
        return dict(seen)

    monkeypatch.setattr(orch_mod, "make_agents", factory)
    wd = tmp_path / "w"
    wd.mkdir(parents=True)
    (wd / "tenure.toml").write_text('test_command = "none"\n' + toml, encoding="utf-8")
    rc = main(["run", "t", "--workdir", str(wd), "--mock", "--debate-rounds", "0", *extra])
    [rd] = list_run_dirs(wd)
    return rc, seen, RunState.load(rd), rd


# 1라운드 I1 → 2라운드에 같은 지적을 ID 없이 다른 말로 다시 씀(I2) → 3라운드 승인
RECUR = [verdict(finding()), verdict(finding(title="공백만 있는 입력에서 예외")), verdict()]


def test_same_issue_without_id_is_merged(tmp_path, monkeypatch, capsys):
    d = MockAdapter(label="dedup", responder=dedup_says([{"new_id": "I2", "old_id": "I1", "reason": "같은 결함"}]))
    rc, seen, st, rd = run(tmp_path, monkeypatch, RECUR, dedup_adapter=d)
    assert rc == 0 and len(st.review_history) == 3
    assert st.dedup["2:codex"]["same"] == 1 and st.review_history[1]["blocking"] == 1
    assert [(x["id"], x["status"], x["closed_round"]) for x in st.issues] == [("I1", "resolved", 3)]
    [call] = d.calls
    assert call.step == "dedup" and call.output_schema == dedup.DEDUP_SCHEMA
    assert "- I2 [P2] 공백만 있는 입력에서 예외" in call.prompt
    assert "- I1 [P2] 빈 입력 처리 없음 — `main.py` (지난 라운드 지적, 이번 리뷰에서 ID 로 다시 적지 않음)" in call.prompt
    review2 = (rd / st.review_history[1]["file"]).read_text(encoding="utf-8")
    assert "[I1]" in review2 and "I2 → I1 와 같은 지적" in review2 and "dedup: 재제기 0 재발 0 합침 1" in review2
    dcall = [c for c in st.calls if c.step == "dedup"][0]
    assert dcall.agent == "claude" and dcall.role == "dedup"
    assert "I2→I1" in capsys.readouterr().out


def test_recurrence_after_resolution(tmp_path, monkeypatch):
    reviews = [verdict(finding()), verdict(finding(title="출력 형식이 다름")),
               verdict(finding(title="공백 입력에서 예외")), verdict()]
    answers = [[], [{"new_id": "I3", "old_id": "I1", "reason": "해결됐던 결함이 다시 보임"}]]
    d = MockAdapter(label="dedup", responder=lambda req, n: json.dumps({"matches": answers[min(n, 2) - 1]}))
    rc, seen, st, rd = run(tmp_path, monkeypatch, reviews, "--max-review", "4", "--stall-rounds", "0", dedup_adapter=d)
    assert rc == 0 and len(d.calls) == 2
    assert st.dedup["3:codex"]["recurred"] == 1 and st.review_history[2]["blocking"] == 1   # 재발은 막는다
    review3 = (rd / st.review_history[2]["file"]).read_text(encoding="utf-8")
    assert "I1 재발(회귀 가능성)" in review3
    reviews_sent = [c for c in seen["codex"].calls if c.step == "review"]
    assert "[이미 닫힌 지적]" not in reviews_sent[1].prompt
    assert "[이미 닫힌 지적]" in reviews_sent[2].prompt and "- I1 [P2] 빈 입력 처리 없음 — `main.py` (2라운드에 해결됨)" in reviews_sent[2].prompt
    fix4 = [c for c in seen["claude"].calls if c.step == "fix"][-1]
    assert "[이미 닫힌 지적] 아래 지적을 고친 코드를 되돌리지 마라" in fix4.prompt


def test_dedup_skipped_without_closed_issues(tmp_path, monkeypatch):
    d = MockAdapter(label="dedup")
    rc, _, st, _ = run(tmp_path, monkeypatch, [verdict(finding()), verdict(finding("I1")), verdict()], dedup_adapter=d)
    assert d.calls == [] and st.dedup == {}                          # I1 이 계속 열려 있어 닫힌 지적이 없다


def test_dedup_failure_does_not_fail_run(tmp_path, monkeypatch, capsys):
    d = MockAdapter(label="dedup", fail_on_calls={1, 2, 3, 4})
    rc, _, st, _ = run(tmp_path, monkeypatch, RECUR, dedup_adapter=d)
    assert rc == 0 and st.status == "done_approved" and st.dedup["2:codex"] == {"result": "failed"}
    assert "보조 호출" in capsys.readouterr().out


def test_dedup_off(tmp_path, monkeypatch):
    rc, seen, st, _ = run(tmp_path, monkeypatch, RECUR, toml="dedup = false\n")
    assert "dedup" not in seen and st.dedup == {} and st.config["dedup"] is False
    assert all("[이미 닫힌 지적]" not in c.prompt for c in seen["codex"].calls + seen["claude"].calls)


def test_default_mock_dedup_added(tmp_path, monkeypatch):
    rc, _, st, _ = run(tmp_path, monkeypatch, RECUR)
    assert st.dedup["2:codex"]["matches"] == {}                      # 자동으로 붙은 mock 확인자: 중복 없음
