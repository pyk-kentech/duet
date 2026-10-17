"""M12: 단계별 추론 강도(DESIGN.md 18.1)와 자식 환경 변수 정리(18.2)."""

from __future__ import annotations

import sys
import json
from pathlib import Path

import pytest

from duet.agents.base import AgentRequest, Mode
from duet.agents.claude_code import ClaudeCodeAdapter
from duet.agents.codex import CodexAdapter
from duet.cli import main
from duet.config import (
    AgentConfig,
    Config,
    ConfigError,
    describe_effort,
    load_config,
    parse_step_effort,
)
from duet.orchestrator import CONFIG_KEYS
from duet.runner import env_drops, run_process
from duet.state import latest_run_dir
from duet.testing import run_tests
from tests.conftest import read_dump
from tests.test_ui import server  # noqa: F401 - pytest 픽스처
from tests.helpers import py_cmd


def req(tmp_path: Path, step: str, round_: int = 0, mode=Mode.READ) -> AgentRequest:
    return AgentRequest("안녕", tmp_path, mode, 20, step, round=round_)


def codex_effort_arg(cmd: list[str]) -> str | None:
    for i, a in enumerate(cmd):
        if a == "-c" and cmd[i + 1].startswith("model_reasoning_effort="):
            return cmd[i + 1].split("=", 1)[1].strip('"')
    return None


def claude_effort_arg(cmd: list[str]) -> str | None:
    return cmd[cmd.index("--effort") + 1] if "--effort" in cmd else None


# ====================================================================== 18.1 설정
class TestStepEffortConfig:
    def test_defaults(self):
        cfg = Config()
        assert cfg.codex.effort == "medium"
        assert cfg.codex.step_effort == {"synthesize": "high", "review": "high", "arbitrate": "high"}
        assert cfg.claude.effort == "" and cfg.claude.step_effort == {}

    @pytest.mark.parametrize("step,round_,want", [
        ("propose", 0, "medium"), ("critique", 1, "medium"), ("synthesize", 0, "high"),
        ("implement", 1, "medium"), ("fix", 2, "medium"),
        ("review", 1, "high"), ("review", 2, "medium"), ("review", 5, "medium"),
    ])
    def test_codex_effort_for(self, step, round_, want):
        assert Config().codex.effort_for(step, round_) == want

    def test_rereview_key_independent_of_review(self):
        ac = AgentConfig(bin="x", effort="low", step_effort={"review": "high", "rereview": "xhigh"})
        assert ac.effort_for("review", 1) == "high"
        assert ac.effort_for("review", 3) == "xhigh"
        assert AgentConfig(bin="x").effort_for("review", 1) == ""

    def test_effort_only_layer_clears_step_effort(self):
        cfg = load_config(None, {"codex.effort": "xhigh"}, global_defaults={})
        assert cfg.codex.step_effort == {}
        assert cfg.codex.effort_for("review", 1) == "xhigh"
        assert cfg.codex.effort_for("synthesize") == "xhigh"

    def test_empty_effort_means_cli_default(self):
        cfg = load_config(None, {"codex.effort": ""}, global_defaults={})
        assert cfg.codex.effort_for("review", 1) == ""

    def test_both_in_same_layer(self):
        cfg = load_config(None, {"codex.effort": "low", "codex.step_effort": {"review": "high"}},
                          global_defaults={})
        assert cfg.codex.effort_for("fix", 1) == "low"
        assert cfg.codex.effort_for("review", 1) == "high"
        assert cfg.codex.effort_for("synthesize") == "low"  # 통째로 교체: 기본값의 synthesize 는 사라짐

    def test_step_effort_only_keeps_lower_effort(self):
        cfg = load_config(None, {"codex.step_effort": {"fix": "low"}}, global_defaults={})
        assert cfg.codex.effort == "medium" and cfg.codex.step_effort == {"fix": "low"}

    def test_layers_toml_and_global(self, tmp_path: Path):
        (tmp_path / "duet.toml").write_text('[codex]\neffort = "high"\n', encoding="utf-8")
        cfg = load_config(tmp_path, global_defaults={"codex": {"step_effort": {"fix": "low"}}})
        assert cfg.codex.effort == "high" and cfg.codex.step_effort == {}
        (tmp_path / "duet.toml").write_text('[codex.step_effort]\nreview = "xhigh"\n', encoding="utf-8")
        cfg = load_config(tmp_path, global_defaults={"codex": {"effort": "low"}})
        assert cfg.codex.effort == "low" and cfg.codex.step_effort == {"review": "xhigh"}

    @pytest.mark.parametrize("bad", [{"deploy": "high"}, {"review": ""}, {"review": "hi gh"}, {"review": 3}])
    def test_validation(self, bad):
        with pytest.raises(ConfigError):
            load_config(None, {"codex.step_effort": bad}, global_defaults={})

    def test_parse_step_effort(self):
        assert parse_step_effort("review=high, fix=low,") == {"review": "high", "fix": "low"}
        for bad in ("review", "review=", "=high"):
            with pytest.raises(ConfigError):
                parse_step_effort(bad)

    def test_describe_effort(self):
        assert describe_effort(Config().codex) == "medium; synthesize·review·arbitrate=high"
        assert describe_effort(AgentConfig(bin="x", effort="xhigh")) == "xhigh"
        assert describe_effort(AgentConfig(bin="x")) == ""
        assert describe_effort(AgentConfig(bin="x", step_effort={"fix": "low"})) == "기본; fix=low"

    def test_old_run_config_resumes_uniform(self):
        # M12 이전 run.json: step_effort 키가 없고 effort 는 "" 로 저장됨 → 예전처럼 CLI 기본값
        old = {"codex.effort": "", "claude.effort": "", "codex.step_effort": None}
        cfg = load_config(None, old, global_defaults={})
        assert cfg.codex.effort_for("review", 1) == "" and cfg.codex.step_effort == {}


# ====================================================================== 18.1 어댑터
class TestStepEffortAdapters:
    def test_codex_command_per_step(self, fake_cfg: Config, tmp_path: Path):
        a = CodexAdapter(fake_cfg)
        out = tmp_path / "last.md"
        assert codex_effort_arg(a.build_command(req(tmp_path, "review", 1), out)[0]) == "high"
        assert codex_effort_arg(a.build_command(req(tmp_path, "review", 2), out)[0]) == "medium"
        assert codex_effort_arg(a.build_command(req(tmp_path, "synthesize"), out)[0]) == "high"
        assert codex_effort_arg(a.build_command(req(tmp_path, "fix", 2, Mode.WRITE), out)[0]) == "medium"

    def test_claude_command_per_step(self, fake_cfg: Config, tmp_path: Path):
        cfg = load_config(None, {"claude": {"bin": fake_cfg.claude.bin, "step_effort": {"fix": "low"}}},
                          global_defaults={})
        a = ClaudeCodeAdapter(cfg)
        assert claude_effort_arg(a.build_command(req(tmp_path, "fix", 2, Mode.WRITE))[0]) == "low"
        assert claude_effort_arg(a.build_command(req(tmp_path, "propose"))[0]) is None

    def test_codex_ask_sends_step_effort(self, fake_cfg: Config, tmp_path: Path, dump_path, monkeypatch):
        monkeypatch.setenv("DUET_FAKE_DUMP", str(dump_path))
        CodexAdapter(fake_cfg).ask(req(tmp_path, "review", 3))
        assert codex_effort_arg(read_dump(dump_path)["argv"]) == "medium"

    def test_claude_usage_records_step_effort(self, fake_cfg: Config, tmp_path: Path):
        cfg = load_config(None, {"claude": {"bin": fake_cfg.claude.bin, "step_effort": {"review": "max"}}},
                          global_defaults={})
        r = ClaudeCodeAdapter(cfg).ask(req(tmp_path, "review", 1))
        assert r.usage is not None and r.usage["effort"] == "max"


# ====================================================================== 18.1 실행 상태·CLI·UI
def test_run_snapshot_and_cli_flag(tmp_path: Path):
    assert "codex.step_effort" in CONFIG_KEYS and "claude.step_effort" in CONFIG_KEYS
    wd = tmp_path / "w"
    rc = main(["run", "할일 CLI", "--workdir", str(wd), "--mock", "--design-only",
               "--codex-step-effort", "review=xhigh,fix=low"])
    assert rc == 0
    run_dir = latest_run_dir(wd)
    conf = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["config"]
    assert conf["codex.effort"] == "medium"
    assert conf["codex.step_effort"] == {"review": "xhigh", "fix": "low"}
    assert conf["claude.step_effort"] == {}
    console = (run_dir / "console.log").read_text(encoding="utf-8")
    assert "(medium; fix=low, review=xhigh)" in console


def test_cli_bad_step_effort(tmp_path: Path, capsys):
    assert main(["run", "x", "--workdir", str(tmp_path / "w"), "--mock", "--codex-step-effort", "review"]) == 2
    assert "review=high" in capsys.readouterr().err


def test_ui_defaults_hide_effort_when_step_routed(server):  # noqa: F811
    d = server.dashboard._defaults(None)
    assert d["codex"]["effort"] == "" and d["codex"]["effort_label"] == "medium; synthesize·review·arbitrate=high"
    assert d["claude"]["effort"] == ""


# ====================================================================== 18.2 환경 변수
ENV = {"HOME": "/h", "PATH": "/bin", "ANTHROPIC_API_KEY": "a", "GH_TOKEN": "g", "my_db_password": "p",
       "CLAUDE_CODE_OAUTH_TOKEN": "o", "AWS_SECRET_ACCESS_KEY": "s", "SSH_AUTH_SOCK": "/s",
       "OPENAI_API_KEY": "k", "TOKENIZERS_PARALLELISM": "false", "CI": "1"}


def test_env_drops_defaults():
    cfg = Config()
    dropped = env_drops(cfg.env_strip, cfg.env_keep, ENV)
    assert dropped == sorted(["ANTHROPIC_API_KEY", "GH_TOKEN", "my_db_password", "AWS_SECRET_ACCESS_KEY",
                              "SSH_AUTH_SOCK", "OPENAI_API_KEY"])
    assert env_drops([], [], ENV) == []
    assert "CLAUDE_CODE_OAUTH_TOKEN" in env_drops(cfg.env_strip, [], ENV)


def test_env_config_validation():
    with pytest.raises(ConfigError):
        load_config(None, {"env_strip": ["X", ""]}, global_defaults={})
    with pytest.raises(ConfigError):
        load_config(None, {"env_keep": "X"}, global_defaults={})


def test_run_process_drop_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DUET_T_SECRET", "s")
    r = run_process([sys.executable, "-c", "import os; print(os.environ.get('DUET_T_SECRET', 'unset'), "
                     "os.environ.get('DUET_T_GIVEN', 'unset'))"], tmp_path,
                    env={"DUET_T_GIVEN": "g"}, drop_env=["DUET_T_SECRET", "DUET_T_GIVEN"])
    assert r.stdout.strip() == "unset g"  # 직접 준 값은 남는다


@pytest.mark.parametrize("adapter_cls,key", [(ClaudeCodeAdapter, "ANTHROPIC_API_KEY"),
                                             (CodexAdapter, "OPENAI_API_KEY")])
def test_adapters_strip_secrets(adapter_cls, key, fake_cfg: Config, tmp_path: Path, dump_path, monkeypatch):
    monkeypatch.setenv("DUET_FAKE_DUMP", str(dump_path))
    monkeypatch.setenv(key, "sk-test")
    monkeypatch.setenv("GH_TOKEN", "ghp-test")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-test")
    adapter_cls(fake_cfg).ask(req(tmp_path, "propose"))
    env = read_dump(dump_path)["env"]
    assert key not in env and "GH_TOKEN" not in env
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth-test" and env["DUET_FAKE_DUMP"] == str(dump_path)


def test_adapter_env_strip_empty_inherits(fake_cfg: Config, tmp_path: Path, dump_path, monkeypatch):
    monkeypatch.setenv("DUET_FAKE_DUMP", str(dump_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    cfg = load_config(None, {"claude": {"bin": fake_cfg.claude.bin}, "env_strip": []}, global_defaults={})
    ClaudeCodeAdapter(cfg).ask(req(tmp_path, "propose"))
    assert read_dump(dump_path)["env"]["ANTHROPIC_API_KEY"] == "sk-test"


def test_run_tests_drop_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "ghp-test")
    cfg = Config()
    no_token = "import os, sys; sys.exit(0 if not os.environ.get('GH_TOKEN') and os.environ.get('CI') == '1' else 1)"
    r = run_tests(tmp_path, py_cmd(no_token), "test", 30, drop_env=env_drops(cfg.env_strip, cfg.env_keep))
    assert r.status == "passed"
    assert run_tests(tmp_path, py_cmd(no_token), "test", 30).status == "failed"


def test_doctor_api_key_check(monkeypatch):
    from duet import doctor

    for k in doctor.API_KEY_VARS:
        monkeypatch.delenv(k, raising=False)
    assert doctor._api_key_check() is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    c = doctor._api_key_check()
    assert c.status == "warn" and c.extra == {"present": ["ANTHROPIC_API_KEY"], "passed": []}
    assert "빼고 넘기지만" in c.detail
    monkeypatch.setattr("duet.config.load_config", lambda *a, **k: Config(env_strip=[]))
    c = doctor._api_key_check()
    assert c.extra["passed"] == ["ANTHROPIC_API_KEY"] and "과금될 수 있습니다" in c.detail
