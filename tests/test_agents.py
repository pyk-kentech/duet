"""어댑터 테스트: 명령어 조립(모드별 플래그), 출력 파싱, 비정상 종료, 한도 감지, 타임아웃.

실제 claude/codex 는 절대 호출하지 않는다. tests/fake_bin 의 가짜 실행 파일을 쓴다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from duet.agents import make_agents
from duet.agents.base import AgentNotAvailable, AgentRequest, Mode
from duet.agents.claude_code import ClaudeCodeAdapter
from duet.agents.codex import CodexAdapter
from duet.agents.mock import MockAdapter
from duet.config import Config, load_config
from duet.runner import run_process
from tests.conftest import read_dump


def req(tmp_path: Path, prompt="안녕", mode=Mode.READ, timeout=20, step="propose") -> AgentRequest:
    return AgentRequest(prompt=prompt, cwd=tmp_path, mode=mode, timeout_sec=timeout, step=step)


# ====================================================================== claude
class TestClaude:
    def test_read_command(self, fake_cfg: Config, tmp_path: Path):
        a = ClaudeCodeAdapter(fake_cfg)
        cmd, stdin = a.build_command(req(tmp_path, mode=Mode.READ))
        assert stdin is None
        assert cmd[0].endswith("fake_bin/claude")
        assert cmd[1:] == ["-p", "--output-format", "json", "--allowedTools", "Read,Glob,Grep", "--", "안녕"]

    def test_write_command(self, fake_cfg: Config, tmp_path: Path):
        a = ClaudeCodeAdapter(fake_cfg)
        cmd, _ = a.build_command(req(tmp_path, mode=Mode.WRITE))
        assert "--permission-mode" in cmd and "acceptEdits" in cmd
        assert "Read,Edit,Write,Glob,Grep,Bash" in cmd
        assert "Read,Glob,Grep" not in cmd

    def test_ask_parses_json_result(self, fake_cfg: Config, tmp_path: Path, dump_path, monkeypatch):
        monkeypatch.setenv("DUET_FAKE_DUMP", str(dump_path))
        monkeypatch.setenv("DUET_FAKE_TEXT", "# 설계안\n내용")
        r = ClaudeCodeAdapter(fake_cfg).ask(req(tmp_path, mode=Mode.WRITE))
        assert r.ok and r.exit_code == 0
        assert r.text == "# 설계안\n내용"
        assert not r.rate_limited and not r.timed_out
        d = read_dump(dump_path)
        assert d["argv"][-1] == "안녕"
        assert d["stdin"] is None
        assert Path(d["cwd"]).resolve() == tmp_path.resolve()
        assert "--permission-mode" in d["argv"]

    def test_long_prompt_goes_to_stdin(self, fake_cfg: Config, tmp_path: Path, dump_path, monkeypatch):
        monkeypatch.setenv("DUET_FAKE_DUMP", str(dump_path))
        cfg = load_config(None, {"claude": {"bin": fake_cfg.claude.bin}, "prompt_arg_max_chars": 100})
        long_prompt = "가" * 101
        a = ClaudeCodeAdapter(cfg)
        cmd, stdin = a.build_command(req(tmp_path, prompt=long_prompt))
        assert stdin == long_prompt and long_prompt not in cmd
        r = a.ask(req(tmp_path, prompt=long_prompt))
        assert r.ok
        d = read_dump(dump_path)
        assert d["stdin"] == long_prompt
        assert d["argv"][-1] == "Read,Glob,Grep"  # 위치 인자 없음

    def test_garbage_output_falls_back_to_stdout(self, fake_cfg: Config, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("DUET_FAKE_SCENARIO", "garbage")
        r = ClaudeCodeAdapter(fake_cfg).ask(req(tmp_path))
        assert r.ok and r.text == "this is not json"

    def test_empty_output(self, fake_cfg: Config, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("DUET_FAKE_SCENARIO", "empty")
        r = ClaudeCodeAdapter(fake_cfg).ask(req(tmp_path))
        assert r.ok and r.text == ""

    def test_parse_output_variants(self):
        p = ClaudeCodeAdapter.parse_output
        assert p('{"result": " hi "}') == "hi"
        assert p('{"no_result": 1}') == '{"no_result": 1}'
        assert p("[1,2]") == "[1,2]"
        assert p("") == ""
        full = ClaudeCodeAdapter.parse_output_full
        assert full('{"result": "Invalid API key", "is_error": true}') == ("Invalid API key", True)
        assert full('{"result": "ok", "is_error": false}') == ("ok", False)

    def test_json_is_error_counts_as_failure(self, fake_cfg: Config, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("DUET_FAKE_SCENARIO", "json_error")
        r = ClaudeCodeAdapter(fake_cfg).ask(req(tmp_path))
        assert not r.ok and r.exit_code == 1 and r.text == "Invalid API key · Fix external API key"

    def test_prompt_not_swallowed_by_variadic_option(self, fake_cfg: Config, tmp_path: Path, dump_path, monkeypatch):
        # 가짜 claude 는 실제처럼 --allowedTools 가 뒤따르는 인자를 삼킨다. `--` 가 없으면 실패해야 한다.
        monkeypatch.setenv("DUET_FAKE_DUMP", str(dump_path))
        r = ClaudeCodeAdapter(fake_cfg).ask(req(tmp_path, prompt="프롬프트"))
        assert r.ok
        d = read_dump(dump_path)
        assert d["argv"][-2:] == ["--", "프롬프트"]
        bad = run_process([fake_cfg.claude.bin, "-p", "--allowedTools", "Read,Glob,Grep", "프롬프트"], cwd=tmp_path)
        assert bad.exit_code == 1 and "Input must be provided" in bad.stderr

    def test_failure(self, fake_cfg: Config, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("DUET_FAKE_SCENARIO", "fail")
        r = ClaudeCodeAdapter(fake_cfg).ask(req(tmp_path))
        assert not r.ok and r.exit_code == 1
        assert "went wrong" in r.raw_stderr
        assert r.failure_reason().startswith("비정상 종료")

    def test_rate_limit_detected(self, fake_cfg: Config, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("DUET_FAKE_SCENARIO", "rate_limit")
        r = ClaudeCodeAdapter(fake_cfg).ask(req(tmp_path))
        assert r.rate_limited and not r.ok
        assert r.failure_reason() == "구독 한도 도달"

    def test_rate_limit_in_json_result(self, fake_cfg: Config, tmp_path: Path, monkeypatch):
        # exit 0 이지만 본문에 한도 문구가 있는 경우도 잡는다
        monkeypatch.setenv("DUET_FAKE_TEXT", "You've hit your weekly limit. resets at 3pm")
        r = ClaudeCodeAdapter(fake_cfg).ask(req(tmp_path))
        assert r.rate_limited and not r.ok

    def test_timeout(self, fake_cfg: Config, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("DUET_FAKE_SCENARIO", "hang")
        r = ClaudeCodeAdapter(fake_cfg).ask(req(tmp_path, timeout=1))
        assert r.timed_out and not r.ok
        assert r.failure_reason() == "시간 초과"

    def test_check_ok(self, fake_cfg: Config):
        ClaudeCodeAdapter(fake_cfg).check()

    def test_check_missing_binary(self):
        cfg = load_config(None, {"claude": {"bin": "no-such-claude-xyz"}})
        with pytest.raises(AgentNotAvailable) as e:
            ClaudeCodeAdapter(cfg).check()
        assert "no-such-claude-xyz" in str(e.value)
        assert "설치" in str(e.value)

    def test_custom_flags_from_config(self, fake_cfg: Config, tmp_path: Path):
        cfg = load_config(None, {"claude": {"bin": fake_cfg.claude.bin, "read_args": ["--tools", "Read"]}})
        cmd, _ = ClaudeCodeAdapter(cfg).build_command(req(tmp_path))
        assert cmd[-4:] == ["--tools", "Read", "--", "안녕"]


# ====================================================================== codex
class TestCodex:
    def test_read_command(self, fake_cfg: Config, tmp_path: Path):
        a = CodexAdapter(fake_cfg)
        cmd, stdin = a.build_command(req(tmp_path, mode=Mode.READ), Path("/tmp/last.md"))
        assert stdin is None
        assert cmd[0].endswith("fake_bin/codex")
        assert cmd[1:] == [
            "exec", "--skip-git-repo-check",
            "-C", str(tmp_path),
            "--sandbox", "read-only",
            "--output-last-message", "/tmp/last.md",
            "안녕",
        ]

    def test_write_command(self, fake_cfg: Config, tmp_path: Path):
        cmd, _ = CodexAdapter(fake_cfg).build_command(req(tmp_path, mode=Mode.WRITE), Path("/tmp/l.md"))
        assert "workspace-write" in cmd and "read-only" not in cmd

    def test_ask_reads_last_message(self, fake_cfg: Config, tmp_path: Path, dump_path, monkeypatch):
        monkeypatch.setenv("DUET_FAKE_DUMP", str(dump_path))
        monkeypatch.setenv("DUET_FAKE_TEXT", "리뷰 결과\n<verdict>\nstatus: APPROVED\nmust_fix: 0\n</verdict>")
        r = CodexAdapter(fake_cfg).ask(req(tmp_path, mode=Mode.WRITE))
        assert r.ok
        assert r.text.startswith("리뷰 결과") and r.text.endswith("</verdict>")
        assert "[fake codex]" in r.raw_stdout
        d = read_dump(dump_path)
        assert d["argv"][-1] == "안녕"
        assert d["argv"][d["argv"].index("-C") + 1] == str(tmp_path)
        assert "workspace-write" in d["argv"]
        # 임시 파일은 정리됨
        out = d["argv"][d["argv"].index("--output-last-message") + 1]
        assert not Path(out).exists()

    def test_long_prompt_goes_to_stdin(self, fake_cfg: Config, tmp_path: Path, dump_path, monkeypatch):
        monkeypatch.setenv("DUET_FAKE_DUMP", str(dump_path))
        cfg = load_config(None, {"codex": {"bin": fake_cfg.codex.bin}, "prompt_arg_max_chars": 100})
        long_prompt = "나" * 500
        r = CodexAdapter(cfg).ask(req(tmp_path, prompt=long_prompt))
        assert r.ok
        d = read_dump(dump_path)
        assert d["argv"][-1] == "-"
        assert d["stdin"] == long_prompt
        assert "prompt_len=500" in r.raw_stdout

    def test_empty_last_message_falls_back_to_stdout(self, fake_cfg: Config, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("DUET_FAKE_SCENARIO", "empty")
        r = CodexAdapter(fake_cfg).ask(req(tmp_path))
        assert r.ok and "stdout fallback text" in r.text

    def test_failure(self, fake_cfg: Config, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("DUET_FAKE_SCENARIO", "fail")
        r = CodexAdapter(fake_cfg).ask(req(tmp_path))
        assert not r.ok and r.exit_code == 1 and r.text == ""

    def test_rate_limit_detected(self, fake_cfg: Config, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("DUET_FAKE_SCENARIO", "rate_limit")
        r = CodexAdapter(fake_cfg).ask(req(tmp_path))
        assert r.rate_limited and not r.ok

    def test_timeout(self, fake_cfg: Config, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("DUET_FAKE_SCENARIO", "hang")
        r = CodexAdapter(fake_cfg).ask(req(tmp_path, timeout=1))
        assert r.timed_out and not r.ok

    def test_check_ok(self, fake_cfg: Config):
        CodexAdapter(fake_cfg).check()

    def test_check_missing_binary(self):
        cfg = load_config(None, {"codex": {"bin": "no-such-codex-xyz"}})
        with pytest.raises(AgentNotAvailable, match="no-such-codex-xyz"):
            CodexAdapter(cfg).check()


# ====================================================================== mock
class TestMock:
    def test_dispatch_by_step(self, tmp_path: Path):
        m = MockAdapter(label="claude")
        assert m.name == "mock-claude"
        m.check()
        assert "설계안" in m.ask(req(tmp_path, step="propose")).text
        assert "## 개정안" in m.ask(req(tmp_path, step="critique")).text
        assert "## 결정 사항" in m.ask(req(tmp_path, step="synthesize")).text
        assert len(m.calls) == 3

    def test_write_touches_file(self, tmp_path: Path):
        m = MockAdapter(label="codex")
        m.ask(req(tmp_path, step="implement", mode=Mode.WRITE))
        assert (tmp_path / "main.py").read_text() == "print('hi')\n"
        m.ask(req(tmp_path, step="fix", mode=Mode.WRITE))
        assert (tmp_path / "main.py").read_text().endswith("# fix\n")
        # READ 모드면 파일을 건드리지 않는다
        before = (tmp_path / "main.py").read_text()
        m.ask(req(tmp_path, step="review", mode=Mode.READ))
        assert (tmp_path / "main.py").read_text() == before

    def test_review_scenario(self, tmp_path: Path):
        m = MockAdapter(label="codex", approve_on_review=2)
        r1 = m.ask(req(tmp_path, step="review"))
        r2 = m.ask(req(tmp_path, step="review"))
        assert "status: CHANGES_REQUESTED" in r1.text
        assert "status: APPROVED" in r2.text

    def test_never_approve(self, tmp_path: Path):
        m = MockAdapter(label="codex", approve_on_review=0)
        for _ in range(5):
            assert "CHANGES_REQUESTED" in m.ask(req(tmp_path, step="review")).text

    def test_failure_injection(self, tmp_path: Path):
        m = MockAdapter(fail_on_calls={1}, rate_limit_on_calls={2}, timeout_on_calls={3})
        r1, r2, r3, r4 = (m.ask(req(tmp_path)) for _ in range(4))
        assert r1.exit_code == 1 and not r1.ok
        assert r2.rate_limited
        assert r3.timed_out
        assert r4.ok

    def test_custom_responder(self, tmp_path: Path):
        m = MockAdapter(responder=lambda rq, n: f"{rq.step}#{n}")
        assert m.ask(req(tmp_path, step="x")).text == "x#1"
        assert m.ask(req(tmp_path, step="y")).text == "y#2"


# ====================================================================== factory
def test_make_agents_real(fake_cfg: Config):
    agents = make_agents(fake_cfg)
    assert isinstance(agents["claude"], ClaudeCodeAdapter)
    assert isinstance(agents["codex"], CodexAdapter)
    assert agents["claude"].name == "claude" and agents["codex"].name == "codex"


def test_make_agents_mock(fake_cfg: Config):
    agents = make_agents(fake_cfg, mock=True)
    assert all(isinstance(a, MockAdapter) for a in agents.values())
    assert agents["claude"].name == "mock-claude"
