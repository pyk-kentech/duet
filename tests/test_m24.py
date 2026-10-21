"""M24: 단계별 모델·추론 강도 (DESIGN.md 30장)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import tenure.orchestrator as orch_mod
from tenure.agents import make_agents
from tenure.agents.base import AgentRequest, Mode
from tenure.agents.claude_code import ClaudeCodeAdapter
from tenure.agents.codex import CodexAdapter
from tenure.agents.mock import MockAdapter
from tenure.cli import main
from tenure.config import (
    Config, ConfigError, apply_step_overrides, describe_model, load_config, parse_set_step,
)
from tenure.state import RunState, list_run_dirs
from tenure.ui.dashboard import ApiError, Dashboard
from tenure.workflow import load_workflow


# ====================================================================== 30.2 에이전트 층
def test_model_for_and_rereview():
    ac = replace(Config().claude, model="claude-opus-5-5",
                 step_model={"implement": "claude-sonnet-5-5", "rereview": "claude-haiku-5-5"})
    assert ac.model_for("implement") == "claude-sonnet-5-5"
    assert ac.model_for("propose") == "claude-opus-5-5"
    assert ac.model_for("review", 1) == "claude-opus-5-5" and ac.model_for("review", 2) == "claude-haiku-5-5"
    assert describe_model(ac) == "claude-opus-5-5; implement=claude-sonnet-5-5, rereview=claude-haiku-5-5"
    assert describe_model(Config().claude) == "기본"


def test_layer_rule_model_clears_step_model(tmp_path: Path):
    (tmp_path / "tenure.toml").write_text('[claude]\nstep_model = { implement = "claude-sonnet-5-5" }\n', encoding="utf-8")
    assert load_config(tmp_path).claude.model_for("implement") == "claude-sonnet-5-5"
    # 위 층이 model 만 정하면 모든 단계 그 모델 (18.1 과 같은 층 규칙)
    cfg = load_config(tmp_path, {"claude.model": "claude-opus-5-5"})
    assert cfg.claude.step_model == {} and cfg.claude.model_for("implement") == "claude-opus-5-5"
    with pytest.raises(ConfigError, match="step_model 의 단계"):
        load_config(None, {"claude.step_model": {"nope": "x"}})
    with pytest.raises(ConfigError, match="step_model.implement 값"):
        load_config(None, {"claude.step_model": {"implement": "a b"}})


FAST_WF = """name = "fast"
description = "작은 모델 구현자"

[roles.fast]
agent = "claude"
model = "claude-sonnet-5-5"

[roles.codex]
agent = "codex"

[[steps]]
kind = "build"
implementer = "fast"
reviewers = ["codex"]
"""


def fast_workflow(tmp_path: Path, cfg):
    p = tmp_path / "fast.toml"
    p.write_text(FAST_WF, encoding="utf-8")
    return load_workflow(f"@{p}", None, cfg)


def test_role_rules_and_explore_audit_keys(tmp_path: Path):
    cfg = load_config(None, {"claude.step_model": {"implement": "claude-opus-5-5"}, "claude.step_effort": {"audit": "low"}})
    wf = fast_workflow(tmp_path, cfg)
    # 모델을 정한 역할은 에이전트의 단계별 모델을 물려받지 않는다
    assert wf.roles["fast"].agent_config(cfg).model_for("implement") == "claude-sonnet-5-5"
    assert load_workflow("classic", None, cfg).roles["claude"].agent_config(cfg).model_for("implement") == "claude-opus-5-5"
    assert cfg.claude.effort_for("audit") == "low"


# ====================================================================== 30.3 칸 단위 지정
def test_parse_set_step_and_validate():
    ov = parse_set_step(["fast.implement.model=claude-haiku-5-5", "fast.implement.effort=low", "codex.review.effort=xhigh"])
    assert ov == {"fast": {"implement": {"model": "claude-haiku-5-5", "effort": "low"}}, "codex": {"review": {"effort": "xhigh"}}}
    for bad in ("fast.implement=claude", "fast.implement.model=", "a.b.c.d=x"):
        with pytest.raises(ConfigError, match="--set-step"):
            parse_set_step([bad])
    for ov, msg in (({"w": {"nope": {"model": "x"}}}, "단계"), ({"w": {"part": {"model": "x"}}}, "단계"),
                    ({"w": {"fix": {"temp": "1"}}}, "알 수 없는 키"), ({"w": {"fix": {"model": "a b"}}}, "값이 잘못"),
                    ({"1x": {"fix": {"model": "x"}}}, "역할 이름")):
        with pytest.raises(ConfigError, match=msg):
            load_config(None, {"step_overrides": ov})


def test_overrides_win_last_for_roles_and_classic(tmp_path: Path):
    cfg = load_config(None, {"step_overrides": {"fast": {"implement": {"model": "claude-haiku-5-5", "effort": "low"}},
                                                "codex": {"review": {"model": "gpt-6-astra", "effort": "xhigh"}}}})
    fast = fast_workflow(tmp_path, cfg).roles["fast"].agent_config(cfg)
    assert (fast.model_for("implement"), fast.effort_for("implement")) == ("claude-haiku-5-5", "low")
    assert fast.model_for("fix") == "claude-sonnet-5-5"                       # 다른 단계는 역할 설정 그대로
    # classic: 역할 이름 = 에이전트 이름. 실제 어댑터(make_agents)에도 들어간다
    codex = make_agents(cfg)["codex"].agent_cfg
    assert (codex.model_for("review", 1), codex.effort_for("review", 1)) == ("gpt-6-astra", "xhigh")
    assert codex.effort_for("review", 2) == "medium"                          # rereview 는 따로
    assert apply_step_overrides(cfg.claude, cfg, "claude") == cfg.claude      # 지정 없는 역할은 그대로


def test_adapters_put_step_model_on_command(fake_cfg: Config, tmp_path: Path):
    cfg = replace(fake_cfg, claude=replace(fake_cfg.claude, model="claude-opus-5-5", step_model={"implement": "claude-sonnet-5-5"}),
                  codex=replace(fake_cfg.codex, model="gpt-6.1-sol", step_model={"review": "gpt-6-astra"}))
    c = ClaudeCodeAdapter(cfg)
    cmd, _ = c.build_command(AgentRequest("구현해", tmp_path, Mode.WRITE, 20, "implement", round=1))
    assert cmd[cmd.index("--model") + 1] == "claude-sonnet-5-5"
    cmd, _ = c.build_command(AgentRequest("설계해", tmp_path, Mode.READ, 20, "propose"))
    assert cmd[cmd.index("--model") + 1] == "claude-opus-5-5"
    x = CodexAdapter(cfg)
    cmd, _ = x.build_command(AgentRequest("리뷰해", tmp_path, Mode.READ, 20, "review", round=1), tmp_path / "last.md")
    assert cmd[cmd.index("-m") + 1] == "gpt-6-astra"
    cmd, _ = x.build_command(AgentRequest("리뷰해", tmp_path, Mode.READ, 20, "review", round=2), tmp_path / "last.md")
    assert cmd[cmd.index("-m") + 1] == "gpt-6.1-sol"                         # rereview 지정이 없으면 model


# ====================================================================== 실행: 기록·확인·세션
def run_mock(tmp_path: Path, monkeypatch, *extra: str, reuse: bool = False):
    seen: dict = {}
    wd = tmp_path / "w"
    wd.mkdir(parents=True, exist_ok=True)
    if reuse:
        (wd / "tenure.toml").write_text('review_session = "reuse"\n', encoding="utf-8")

    def factory(cfg, *, mock):
        seen["cfg"] = cfg
        seen["claude"] = MockAdapter(label="claude")
        seen["codex"] = MockAdapter(label="codex", approve_on_review=3)
        return {"claude": seen["claude"], "codex": seen["codex"]}

    monkeypatch.setattr(orch_mod, "make_agents", factory)
    rc = main(["run", "t", "--workdir", str(wd), "--mock", "--debate-rounds", "0", "--max-review", "4", *extra])
    [rd] = list_run_dirs(wd)
    return rc, seen, RunState.load(rd), rd


def test_run_records_step_overrides_and_logs(tmp_path: Path, monkeypatch):
    rc, seen, st, rd = run_mock(tmp_path, monkeypatch, "--set-step", "claude.implement.model=claude-haiku-5-5",
                                "--codex-step-model", "review=gpt-6-astra")
    assert rc == 0
    assert st.config["step_overrides"] == {"claude": {"implement": {"model": "claude-haiku-5-5"}}}
    assert st.config["codex.step_model"] == {"review": "gpt-6-astra"}
    log = (rd / "console.log").read_text(encoding="utf-8")
    assert "implement=claude-haiku-5-5" in log and "review=gpt-6-astra" in log


def test_unknown_role_in_overrides_is_error(tmp_path: Path, monkeypatch, capsys):
    wd = tmp_path / "w"
    rc = main(["run", "t", "--workdir", str(wd), "--mock", "--set-step", "worker.implement.model=claude-haiku-5-5"])
    assert rc != 0 and "worker" in capsys.readouterr().err
    assert not list_run_dirs(wd) if wd.exists() else True


def test_review_session_not_reused_when_model_changes(tmp_path: Path, monkeypatch):
    rc, seen, st, rd = run_mock(tmp_path, monkeypatch, "--codex-step-model", "rereview=gpt-6-luna", reuse=True)
    assert rc == 0
    rv = [c for c in seen["codex"].calls if c.step == "review"]
    # 2회차는 1회차와 모델이 달라 새 세션, 3회차는 (같은 모델인) 2회차 세션을 잇는다
    assert rv[0].resume_session is None and rv[1].resume_session is None and rv[2].resume_session is not None
    assert st.review_sessions["codex"]["model"] == "gpt-6-luna"
    # 같은 모델이면(지정 없음) 예전처럼 이어간다
    rc, seen, st, rd = run_mock(tmp_path / "b", monkeypatch, reuse=True)
    rv = [c for c in seen["codex"].calls if c.step == "review"]
    assert rv[1].resume_session is not None


# ====================================================================== UI
def test_ui_start_run_passes_step_overrides(tmp_path: Path, monkeypatch):
    seen = {}
    monkeypatch.setattr(Dashboard, "_spawn", lambda self, kind, wd, argv: seen.update(argv=argv) or {"id": "j"})
    Dashboard().start_run({"task": "t", "project": str(tmp_path / "p"), "mock": True, "workflow": "secure",
                           "step_overrides": {"security": {"review": {"model": "gpt-6-luna", "effort": ""}},
                                              "codex": {"review": {"effort": "xhigh"}}}})
    argv = seen["argv"]
    pairs = [argv[i + 1] for i, a in enumerate(argv) if a == "--set-step"]
    assert pairs == ["security.review.model=gpt-6-luna", "codex.review.effort=xhigh"]
    with pytest.raises(ApiError, match="manager2"):
        Dashboard().start_run({"task": "t", "project": str(tmp_path / "p"), "mock": True, "workflow": "secure",
                               "step_overrides": {"manager2": {"review": {"model": "x"}}}})
    with pytest.raises(ApiError, match="단계"):
        Dashboard().start_run({"task": "t", "project": str(tmp_path / "p"), "mock": True,
                               "step_overrides": {"claude": {"nope": {"model": "x"}}}})


# ====================================================================== 29장: 분업은 없앴다
def test_extended_removed(tmp_path: Path):
    from tenure.workflow import WorkflowError, list_workflows

    with pytest.raises(WorkflowError):
        load_workflow("extended", None, Config())
    assert "extended" not in [w["id"] for w in list_workflows(None, Config())]
    p = tmp_path / "team.toml"
    p.write_text('name = "team"\n[roles.m]\nagent = "codex"\n[roles.w]\nagent = "claude"\n[roles.r]\nagent = "codex"\n'
                 '[[steps]]\nkind = "build"\nmanager = "m"\nworkers = ["w"]\nreviewers = ["r"]\n', encoding="utf-8")
    with pytest.raises(WorkflowError, match="없앤 기능"):
        load_workflow(f"@{p}", None, Config())


# ====================================================================== 30.6 판단량으로 정한 기본 모델
def test_default_model_tiers():
    cfg = Config()
    assert cfg.claude.model == "" and cfg.codex.model == ""                  # 판단 자리는 CLI 기본(주 모델)
    assert cfg.dedup_model == "claude-haiku-5-5"                              # 중복 확인은 가벼운 모델
    scout = load_workflow("existing", None, cfg).roles["scout"].agent_config(cfg)
    assert (scout.model_for("explore"), scout.effort_for("explore")) == ("gpt-6-luna", "low")
    lean = load_workflow("lean", None, cfg)
    assert lean.roles["claude"].agent_config(cfg).model_for("implement") == "claude-sonnet-5-5"
    assert lean.roles["codex"].agent_config(cfg).model_for("review") == ""   # 리뷰는 추론이 필요해 기본 모델


def test_cli_default_models(tmp_path: Path, monkeypatch):
    from tenure.ui.server import cli_default_models, model_suggestions

    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    assert cli_default_models() == {"claude": None, "codex": None}
    (tmp_path / "codex").mkdir()
    (tmp_path / "codex" / "config.toml").write_text('model = "gpt-6.1-sol"\nmodel_reasoning_effort = "high"\n', encoding="utf-8")
    (tmp_path / "claude").mkdir()
    (tmp_path / "claude" / "settings.json").write_text('{"model": "claude-opus-5-5"}', encoding="utf-8")
    assert cli_default_models() == {"claude": "claude-opus-5-5", "codex": "gpt-6.1-sol"}
    s = model_suggestions()
    assert s["claude"]["cli_default"] == "claude-opus-5-5" and s["codex"]["cli_default"] == "gpt-6.1-sol"
    (tmp_path / "codex" / "config.toml").write_text("not = [toml", encoding="utf-8")
    assert cli_default_models()["codex"] is None                             # 못 읽으면 모름
