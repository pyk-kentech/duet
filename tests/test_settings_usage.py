"""전역 설정, 모델·추론 강도, 사용량 수집, 환경 점검, 터미널 작업."""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import pytest

from tenure.agents.base import AgentRequest, Mode
from tenure.agents.claude_code import ClaudeCodeAdapter
from tenure.agents.codex import CodexAdapter
from tenure.cli import main
from tenure.config import ConfigError, load_config
from tenure.doctor import ACTIONS, ready, run_checks
from tenure.settings import SettingsError, load_settings, save_settings
from tenure.state import RunState, list_run_dirs
from tenure.ui.terminal import TermJob, clean
from tenure.usage import claude_call_usage, claude_local_usage, codex_call_usage, codex_rate_limits
from tests.conftest import read_dump


# ====================================================================== 설정
def test_settings_roundtrip_and_validation(isolated_tenure_home):
    assert load_settings() == {"workspace_roots": [], "defaults": {}, "machines": []}
    data = {"workspace_roots": ["~/projects", "/srv/work"],
            "defaults": {"debate_rounds": 2, "claude": {"model": "opus", "effort": "high"}},
            "machines": [{"id": "lab", "name": "연구실", "ssh": "me@lab.example", "port": 2222}]}
    save_settings(data)
    assert load_settings() == data
    bad = [
        {**data, "workspace_roots": ["relative/x"]},
        {**data, "defaults": {"debate_rounds": 99}},
        {**data, "defaults": {"claude": {"model": "opus; rm -rf /"}}},
        {**data, "machines": [{"id": "Lab!", "ssh": "x"}]},
        {**data, "machines": [{"id": "local", "ssh": "x"}]},
        {**data, "machines": [{"id": "a", "ssh": "-oProxyCommand=evil"}]},
        {**data, "machines": [{"id": "a", "ssh": "h"}, {"id": "a", "ssh": "h2"}]},
    ]
    for b in bad:
        with pytest.raises(SettingsError):
            save_settings(b)


def test_config_layers_precedence(isolated_tenure_home, tmp_path: Path):
    save_settings({"defaults": {"debate_rounds": 2, "max_review": 4, "claude": {"model": "sonnet"}}})
    assert load_config(None).debate_rounds == 2 and load_config(None).claude.model == "sonnet"
    (tmp_path / "tenure.toml").write_text("max_review = 5\n[claude]\neffort = \"low\"\n", encoding="utf-8")
    cfg = load_config(tmp_path, {"claude.model": "opus", "debate_rounds": None})
    assert (cfg.debate_rounds, cfg.max_review, cfg.claude.model, cfg.claude.effort) == (2, 5, "opus", "low")
    with pytest.raises(ConfigError):
        load_config(None, {"codex.effort": "a b"})


def test_broken_settings_file_does_not_break_runs(isolated_tenure_home):
    (isolated_tenure_home / "settings.json").write_text("{not json", encoding="utf-8")
    assert load_config(None).implementer == "claude"


# ====================================================================== 모델 플래그
def test_model_and_effort_flags(fake_cfg, tmp_path: Path, dump_path, monkeypatch):
    monkeypatch.setenv("TENURE_FAKE_DUMP", str(dump_path))
    cfg = load_config(None, {"claude": {"bin": fake_cfg.claude.bin, "model": "opus", "effort": "high"},
                             "codex": {"bin": fake_cfg.codex.bin, "model": "gpt-6.1-sol", "effort": "xhigh"}})
    req = AgentRequest("안녕", tmp_path, Mode.READ, 20, "propose")
    r = ClaudeCodeAdapter(cfg).ask(req)
    argv = read_dump(dump_path)["argv"]
    assert r.ok and argv[argv.index("--model") + 1] == "opus" and argv[argv.index("--effort") + 1] == "high"
    assert argv[-2:] == ["--", "안녕"]
    r = CodexAdapter(cfg).ask(req)
    argv = read_dump(dump_path)["argv"]
    assert r.ok and argv[argv.index("-m") + 1] == "gpt-6.1-sol"
    assert 'model_reasoning_effort="xhigh"' in argv
    # 비우면 플래그를 넣지 않는다
    assert "--model" not in ClaudeCodeAdapter(fake_cfg).build_command(req)[0]
    assert "-m" not in CodexAdapter(fake_cfg).build_command(req, Path("/tmp/x"))[0]


def test_models_saved_in_run_and_reused_on_resume(isolated_tenure_home, tmp_path: Path, monkeypatch, capsys):
    import tenure.orchestrator as orch_mod
    from tenure.agents.mock import MockAdapter

    wd = tmp_path / "x"
    seen = []

    def factory(cfg, *, mock):
        seen.append((cfg.claude.model, cfg.codex.effort))
        fail = {3, 4} if len(seen) == 1 else set()
        return {"claude": MockAdapter(label="claude"), "codex": MockAdapter(label="codex", fail_on_calls=fail, approve_on_review=1)}

    monkeypatch.setattr(orch_mod, "make_agents", factory)
    assert main(["run", "t", "--workdir", str(wd), "--mock", "--debate-rounds", "0",
                 "--claude-model", "opus", "--codex-effort", "high"]) == 3
    assert "모델: claude opus / codex 기본(high)" in capsys.readouterr().out
    st = RunState.load(list_run_dirs(wd)[-1])
    assert st.config["claude.model"] == "opus" and st.config["codex.effort"] == "high"
    save_settings({"defaults": {"claude": {"model": "haiku"}}})   # 나중에 전역 설정을 바꿔도
    assert main(["resume", "--workdir", str(wd)]) == 0
    assert seen == [("opus", "high"), ("opus", "high")]          # resume 은 처음 모델 그대로


# ====================================================================== 사용량
def test_claude_usage_from_json(fake_cfg, tmp_path: Path):
    r = ClaudeCodeAdapter(fake_cfg).ask(AgentRequest("hi", tmp_path, Mode.READ, 20, "propose"))
    limits = r.usage.pop("rate_limits")          # 스트림의 사용률 이벤트 (DESIGN.md 28.6)
    assert r.usage == {"input_tokens": 1110, "cached_input_tokens": 1000, "output_tokens": 50,
                       "reasoning_tokens": 7, "cost_usd": 0.0123, "model": "claude-opus-5-5"}
    assert limits["five_hour"] == {"used_percent": 7.0, "resets_at": 1792224000} and limits["status"] == "allowed"
    assert claude_call_usage({"no": "usage"}) is None


def test_codex_usage_from_session_log(fake_cfg, tmp_path: Path, monkeypatch):
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    wd = tmp_path / "wd"
    wd.mkdir()
    r = CodexAdapter(fake_cfg).ask(AgentRequest("hi", wd, Mode.READ, 20, "review"))
    assert r.usage["input_tokens"] == 2000 and r.usage["output_tokens"] == 300 and r.usage["model"] == "gpt-fake"
    assert r.usage["rate_limits"]["primary"]["used_percent"] == 42.5
    # 다른 폴더나 이전 시각의 세션은 고르지 않음
    assert codex_call_usage(tmp_path / "other", time.time() - 60) is None
    assert codex_call_usage(wd, time.time() + 3600) is None
    lim = codex_rate_limits()
    assert lim["primary"]["used_percent"] == 42.5 and lim["plan_type"] == "pro" and lim["as_of"]


def test_usage_recorded_in_transcript_and_state(fake_bin, tmp_path: Path, monkeypatch, isolated_tenure_home):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    monkeypatch.setenv("TENURE_FAKE_TEXT", "## 결정 사항\n내용")
    (tmp_path / "tenure.toml").write_text(
        f"[claude]\nbin = '{fake_bin / 'claude'}'\n[codex]\nbin = '{fake_bin / 'codex'}'\n", encoding="utf-8")
    assert main(["run", "t", "--workdir", str(tmp_path), "--design-only", "--debate-rounds", "0", "--force"]) == 0
    st = RunState.load(list_run_dirs(tmp_path)[-1])
    totals = st.usage_totals()
    assert totals["claude"]["output_tokens"] == 50 and totals["claude"]["cost_usd"] == 0.0123
    assert totals["codex"]["input_tokens"] == 4000 and totals["codex"]["calls"] == 2
    head = (list_run_dirs(tmp_path)[-1] / "01_propose_claude.md").read_text(encoding="utf-8")
    assert "tokens_out: 50" in head and "model: claude-opus-5-5" in head


def test_claude_local_usage_windows_and_dedupe(tmp_path: Path):
    proj = tmp_path / "projects" / "-x"
    proj.mkdir(parents=True)
    now = dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.timezone.utc)

    def msg(req, hours_ago, out, model="claude-opus-5-5"):
        ts = (now - dt.timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
        return json.dumps({"requestId": req, "timestamp": ts, "message": {
            "model": model, "usage": {"input_tokens": 1, "cache_read_input_tokens": 9, "output_tokens": out}}})

    lines = [msg("a", 1, 100), msg("a", 1, 100), msg("b", 30, 1000, "claude-sonnet-5-5"), msg("c", 24 * 9, 5000), "garbage"]
    (proj / "s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    u = claude_local_usage(now=now, home=tmp_path)
    assert u["windows"]["5시간"] == {"input_tokens": 10, "output_tokens": 100, "messages": 1}
    assert u["windows"]["7일"] == {"input_tokens": 20, "output_tokens": 1100, "messages": 2}
    assert u["output_by_model_7d"] == {"claude-opus-5-5": 100, "claude-sonnet-5-5": 1000}


# ====================================================================== 환경 점검
def test_doctor_with_fake_clis(fake_bin, monkeypatch):
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    checks = {c["id"]: c for c in run_checks()}
    assert checks["claude"]["status"] == "ok" and checks["claude"]["extra"]["subscription"] == "max"
    assert checks["codex"]["status"] == "ok" and "login_codex" not in checks["codex"]["actions"]
    assert checks["git"]["status"] == "ok"
    assert ready(list(checks.values()))
    monkeypatch.setenv("TENURE_FAKE_LOGGED", "0")
    checks = {c["id"]: c for c in run_checks()}
    assert checks["claude"]["status"] == "warn" and checks["claude"]["actions"][0] == "login_claude"
    assert checks["codex"]["status"] == "warn" and checks["codex"]["actions"][0] == "login_codex"
    assert not ready(list(checks.values()))


def test_doctor_cli(fake_bin, monkeypatch, capsys):
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    assert main(["doctor"]) == 0
    assert "Claude Code" in capsys.readouterr().out
    assert main(["doctor", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True


def test_actions_are_fixed_official_commands():
    assert "https://claude.ai/install.sh" in ACTIONS["install_claude"].shell
    assert "https://chatgpt.com/codex/install.sh" in ACTIONS["install_codex"].shell
    assert "https://astral.sh/uv/install.sh" in ACTIONS["install_uv"].shell
    assert ACTIONS["login_codex"].shell == "codex login --device-auth"
    assert ACTIONS["login_claude"].interactive


# ====================================================================== 터미널 작업
def test_term_job_interactive_input():
    # pty(POSIX)·파이프(Windows) 어느 쪽이든 같은 결과 (DESIGN.md 27.5)
    script = ("import sys; sys.stdout.write('code? '); sys.stdout.flush(); x = sys.stdin.readline().strip(); "
              "print('got:' + x, flush=True); print('\\033[31mred\\033[0m https://example.com/auth?x=1', flush=True)")
    job = TermJob(id="t1", title="test", argv=[sys.executable, "-c", script]).start()
    deadline = time.monotonic() + 5
    while "code?" not in job.snapshot()["text"] and time.monotonic() < deadline:
        time.sleep(0.05)
    job.write("ABCD-1234")
    while job.running and time.monotonic() < deadline + 5:
        time.sleep(0.05)
    time.sleep(0.2)
    snap = job.snapshot()
    assert snap["returncode"] == 0 and "got:ABCD-1234" in snap["text"]
    assert "\x1b" not in snap["text"] and "red" in snap["text"]
    assert snap["urls"] == ["https://example.com/auth?x=1"]
    assert job.snapshot(snap["offset"])["text"] == ""
    with pytest.raises(RuntimeError):
        job.write("again")


def test_term_job_kill():
    job = TermJob(id="t2", title="sleep", argv=[sys.executable, "-c", "import time; time.sleep(30)"]).start()
    time.sleep(0.2)
    job.kill()
    deadline = time.monotonic() + 8
    while job.running and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not job.running


def test_clean_ansi():
    assert clean("a\x1b[2K\x1b[1Gb\r\nc\rd\x07") == "ab\nc\nd"
