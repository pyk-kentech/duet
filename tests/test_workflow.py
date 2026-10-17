"""M13: 워크플로 템플릿 (DESIGN.md 19장)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import duet.orchestrator as orch_mod
from duet.agents import make_role_agents
from duet.agents.base import AgentRequest, Mode
from duet.agents.mock import MockAdapter
from duet.cli import main
from duet.config import Config, load_config
from duet.state import DONE_APPROVED, DONE_DESIGN, DONE_UNAPPROVED, STOPPED_RATE_LIMIT, RunState, list_run_dirs
from duet.transcript import Transcript
from duet.workflow import (
    Role,
    Workflow,
    WorkflowError,
    classic,
    list_workflows,
    load_workflow,
    parse_workflow,
)
from tests.helpers import file_names
from tests.test_ui import _job, call, server, wait_for  # noqa: F401 - pytest 픽스처

ROLES = {"a": {"agent": "claude"}, "b": {"agent": "codex"}, "c": {"agent": "codex"}}


def parse(data: dict) -> Workflow:
    return parse_workflow(data, name_hint="t", source="file", where="t.toml")


def wf_data(*steps: dict, roles: dict | None = None) -> dict:
    return {"roles": roles or ROLES, "steps": list(steps)}


BUILD = {"kind": "build", "implementer": "a", "reviewers": ["b"]}
DEBATE = {"kind": "debate", "proposers": ["a", "b"], "synth": "b"}


def write_project_wf(wd: Path, name: str, text: str) -> None:
    d = wd / ".duet" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.toml").write_text(text, encoding="utf-8")


def run(wd: Path, *extra: str) -> int:
    return main(["run", "메모 CLI", "--workdir", str(wd), "--mock", *extra])


def only_run(wd: Path) -> Path:
    [rd] = list_run_dirs(wd)
    return rd


# ====================================================================== 파싱·검증
class TestParse:
    def test_valid(self):
        wf = parse(wf_data({"kind": "explore", "role": "c"}, DEBATE, BUILD, {"kind": "audit", "roles": ["a"]}))
        assert [s.kind for s in wf.steps] == ["explore", "debate", "build", "audit"]
        assert wf.used_roles() == ["c", "a", "b"]
        assert wf.summary() == "explore(c) → debate(a, b → b) → build(a; 리뷰 b) → audit(a)"

    @pytest.mark.parametrize("data,msg", [
        ({"roles": ROLES, "steps": [BUILD], "x": 1}, "알 수 없는 키"),
        ({"roles": {}, "steps": [BUILD]}, "[roles.<이름>]"),
        ({"roles": ROLES, "steps": []}, "[[steps]]"),
        (wf_data(BUILD, roles={"Bad": {"agent": "claude"}}), "역할 이름"),
        (wf_data(BUILD, roles={"a": {"agent": "gemini"}, "b": {"agent": "codex"}}), "agent 는"),
        (wf_data(BUILD, roles={"a": {"agent": "claude", "colour": 1}, "b": {"agent": "codex"}}), "알 수 없는 키"),
        (wf_data(BUILD, roles={"a": {"agent": "claude", "step_effort": {"deploy": "x"}}, "b": {"agent": "codex"}}), "step_effort"),
        (wf_data(BUILD, roles={"a": {"agent": "claude", "templates": {"deploy": "x"}}, "b": {"agent": "codex"}}), "templates"),
        (wf_data(BUILD, roles={"a": {"agent": "claude", "instructions": "x" * 5000}, "b": {"agent": "codex"}}), "instructions"),
        (wf_data({"kind": "deploy"}), "kind"),
        (wf_data({**BUILD, "implementer": "zz"}), "정의되지 않은 역할"),
        (wf_data({**BUILD, "reviewers": ["a"]}), "리뷰어가 될 수 없습니다"),
        (wf_data({**BUILD, "reviewers": ["b", "b"]}), "두 번"),
        (wf_data({**BUILD, "reviewers": []}), "1~3개"),
        (wf_data({**BUILD, "max_review": 11}), "max_review"),
        (wf_data({**BUILD, "extra": 1}), "알 수 없는 키"),
        (wf_data({"kind": "debate", "proposers": ["a", "b"]}, BUILD), "정의되지 않은 역할"),
        (wf_data({"kind": "debate", "proposers": ["a"], "synth": "b"}, BUILD), "synth 를 쓰지 않습니다"),
        (wf_data({"kind": "debate", "proposers": ["a"], "rounds": 1}, BUILD), "rounds"),
        (wf_data(BUILD, DEBATE), "build 앞"),
        (wf_data(BUILD, BUILD), "하나만"),
        (wf_data({"kind": "audit", "roles": ["a"]}, BUILD), "build 뒤"),
        (wf_data(BUILD, {"kind": "explore", "role": "a"}), "explore 단계는 build 앞"),
        (wf_data({"kind": "explore", "role": "a"}, {"kind": "explore", "role": "b"}, BUILD), "id 가 겹칩니다"),
    ])
    def test_errors(self, data, msg):
        with pytest.raises(WorkflowError, match=None) as e:
            parse(data)
        assert msg in str(e.value) and str(e.value).startswith("t.toml:")

    def test_roundtrip_dict(self):
        wf = parse({**wf_data(DEBATE, BUILD), "name": "x", "description": "d"})
        back = Workflow.from_dict(json.loads(json.dumps(wf.to_dict())))
        assert back.to_dict() == wf.to_dict()


class TestRoles:
    def test_agent_config_inherits_and_overrides(self):
        cfg = load_config(None, {"codex.model": "gpt-x"}, global_defaults={})
        assert Role("r", "codex").agent_config(cfg).model == "gpt-x"
        ac = Role("r", "codex", model="m", effort="low").agent_config(cfg)
        assert (ac.model, ac.effort, ac.step_effort) == ("m", "low", {})   # effort 만 → 단계별 비움
        ac = Role("r", "codex", step_effort={"fix": "xhigh"}).agent_config(cfg)
        assert ac.effort == "medium" and ac.step_effort == {"fix": "xhigh"}
        assert ac.bin == cfg.codex.bin and ac.read_args == cfg.codex.read_args

    def test_role_agents_build_commands(self, fake_cfg: Config, tmp_path: Path):
        wf = parse(wf_data(
            {"kind": "build", "implementer": "a", "reviewers": ["b"]},
            roles={"a": {"agent": "claude", "model": "sonnet", "effort": "low"},
                   "b": {"agent": "codex", "effort": "xhigh"}}))
        agents = make_role_agents(fake_cfg, wf)
        cmd, _ = agents["a"].build_command(AgentRequest("x", tmp_path, Mode.WRITE, 5, "implement", round=1))
        assert cmd[cmd.index("--model") + 1] == "sonnet" and cmd[cmd.index("--effort") + 1] == "low"
        cmd, _ = agents["b"].build_command(AgentRequest("x", tmp_path, Mode.READ, 5, "review", round=1), tmp_path / "o")
        assert 'model_reasoning_effort="xhigh"' in cmd

    def test_mock_role_agents(self):
        wf = parse(wf_data(DEBATE, BUILD))
        agents = make_role_agents(Config(), wf, mock=True)
        assert set(agents) == {"a", "b"} and agents["a"].name == "mock-a"


# ====================================================================== 찾기·목록
class TestLoad:
    def test_builtins_and_classic(self, tmp_path: Path):
        ids = [w["id"] for w in list_workflows(None)]
        assert ids[0] == "classic" and {"secure", "existing", "lean"} <= set(ids)
        cfg = load_config(None, {"implementer": "codex", "reviewer": "claude", "synth": "claude",
                                 "debate_rounds": 2}, global_defaults={})
        wf = classic(cfg)
        assert wf.is_classic and wf.steps[0].proposers == ["claude", "codex"] and wf.steps[0].synth == "claude"
        assert wf.steps[1].implementer == "codex" and wf.steps[1].reviewers == ["claude"]
        assert load_workflow("classic", None, cfg).is_classic
        for name in ("secure", "existing", "lean"):
            assert load_workflow(name, None, cfg).source == "builtin"

    def test_project_and_user_shadow_builtin(self, tmp_path: Path, isolated_duet_home: Path):
        wd = tmp_path / "w"
        text = '[roles.a]\nagent = "claude"\n[roles.b]\nagent = "codex"\n[[steps]]\nkind = "build"\nimplementer = "a"\nreviewers = ["b"]\n'
        (isolated_duet_home / "workflows").mkdir()
        (isolated_duet_home / "workflows" / "lean.toml").write_text(text, encoding="utf-8")
        assert load_workflow("lean", wd, Config()).source == "user"
        write_project_wf(wd, "lean", text)
        assert load_workflow("lean", wd, Config()).source == "project"
        write_project_wf(wd, "broken", "[roles")
        rows = {w["id"]: w for w in list_workflows(wd)}
        assert rows["lean"]["source"] == "project" and rows["broken"]["source"] == "error"
        assert "TOML" in rows["broken"]["error"]

    def test_file_spec_and_errors(self, tmp_path: Path):
        p = tmp_path / "mine.toml"
        p.write_text('[roles.a]\nagent = "claude"\n[roles.b]\nagent = "codex"\n[[steps]]\nkind = "build"\n'
                     'implementer = "a"\nreviewers = ["b"]\n', encoding="utf-8")
        wf = load_workflow(f"@{p}", None, Config())
        assert wf.source == "file" and wf.name == "mine"
        with pytest.raises(WorkflowError, match="찾을 수 없습니다"):
            load_workflow("nope", None, Config())
        with pytest.raises(WorkflowError, match="찾을 수 없습니다"):
            load_workflow(f"@{tmp_path / 'none.toml'}", None, Config())

    def test_missing_role_template(self, tmp_path: Path):
        wd = tmp_path / "w"
        write_project_wf(wd, "t", '[roles.a]\nagent = "claude"\n[roles.b]\nagent = "codex"\n'
                                  'templates = { review = "my_review" }\n'
                                  '[[steps]]\nkind = "build"\nimplementer = "a"\nreviewers = ["b"]\n')
        with pytest.raises(WorkflowError, match="my_review"):
            load_workflow("t", wd, Config())
        (wd / ".duet" / "templates").mkdir(parents=True)
        (wd / ".duet" / "templates" / "my_review.md").write_text("리뷰 {task}\n<verdict>\n", encoding="utf-8")
        assert load_workflow("t", wd, Config()).roles["b"].templates == {"review": "my_review"}


# ====================================================================== 실행
def test_classic_run_unchanged(tmp_path: Path):
    wd = tmp_path / "w"
    assert run(wd, "--debate-rounds", "0") == 0
    rd = only_run(wd)
    st = RunState.load(rd)
    assert st.workflow is None and st.config["workflow"] == "classic"
    assert file_names(rd) == ["01_propose_claude.md", "02_propose_codex.md", "03_synthesize_codex.md",
                              "04_impl1_claude.md", "05_review1_codex.md", "06_impl2_claude.md",
                              "07_review2_codex.md", "08_report_claude.md"]
    assert all(c.role is None for c in st.calls if c.step != "report")      # 결과 요약자는 따로 (32장)
    assert "role" not in Transcript(rd).entries()[0].meta


def test_secure_builtin_two_reviewers_and_audit(tmp_path: Path, capsys):
    wd = tmp_path / "w"
    assert run(wd, "--workflow", "secure", "--debate-rounds", "0") == 0
    rd = only_run(wd)
    st = RunState.load(rd)
    assert st.status == DONE_APPROVED and st.workflow["name"] == "secure"
    names = file_names(rd)
    assert names[-7:] == ["05_review1_codex.md", "06_review1_security.md", "07_impl2_claude.md",
                          "08_review2_codex.md", "09_review2_security.md", "10_audit_auditor.md",
                          "11_report_claude.md"]                     # 결과 요약은 감사 뒤
    h1, h2 = st.review_history
    assert not h1["approved"] and h1["blocking"] == 2 and [r["role"] for r in h1["reviewers"]] == ["codex", "security"]
    assert h2["approved"] and h2["files"] == ["08_review2_codex.md", "09_review2_security.md"]
    assert st.last_reviews == {"codex": "08_review2_codex.md", "security": "09_review2_security.md"}
    assert st.audits["audit"][0]["role"] == "auditor" and st.audits["audit"][0]["approved"]
    sec = next(e for e in Transcript(rd).entries() if e.name == "06_review1_security.md")
    assert sec.meta["agent"] == "codex" and sec.meta["role"] == "security"
    assert {(c.agent, c.role) for c in st.calls if c.step == "audit"} == {("claude", "auditor")}
    out = capsys.readouterr().out
    assert "워크플로: secure (내장)" in out and "역할: claude=claude" in out
    assert "판정(security)" in out and "감사 결과(auditor): 문제 없음" in out


def _recording_factory(store: dict, **per_role):
    def factory(cfg, wf, *, mock):
        agents = {n: MockAdapter(label=n, **per_role.get(n, {})) for n in wf.used_roles()}
        store.setdefault("rounds", []).append(agents)
        return agents
    return factory


def test_multi_reviewer_prompts(tmp_path: Path, monkeypatch):
    wd = tmp_path / "w"
    write_project_wf(wd, "two", '''
[roles.dev]
agent = "claude"
instructions = "작은 함수로 나눠라."
[roles.rev]
agent = "codex"
[roles.sec]
agent = "codex"
templates = { review = "review_security" }
[[steps]]
kind = "build"
implementer = "dev"
reviewers = ["rev", "sec"]
max_review = 3
''')
    (wd / "DESIGN.md").write_text("# 설계\n", encoding="utf-8")
    store: dict = {}
    monkeypatch.setattr(orch_mod, "make_role_agents",
                        _recording_factory(store, rev={"approve_on_review": 1}, sec={"approve_on_review": 2}))
    assert run(wd, "--workflow", "two") == 0
    agents = store["rounds"][0]
    dev_calls = agents["dev"].calls
    assert [c.step for c in dev_calls] == ["implement", "fix"]
    assert "작은 함수로 나눠라." in dev_calls[0].prompt
    fix = dev_calls[1].prompt
    assert "### rev 의 리뷰" in fix and "### sec 의 리뷰" in fix
    assert "보안 리뷰어" in agents["sec"].calls[0].prompt and "보안 리뷰어" not in agents["rev"].calls[0].prompt
    st = RunState.load(only_run(wd))
    first = st.review_history[0]
    assert not first["approved"] and [r["approved"] for r in first["reviewers"]] == [True, False]
    assert first["blocking"] == 1 and st.config["max_review"] == 3


def test_existing_explore_feeds_prompts(tmp_path: Path, monkeypatch):
    wd = tmp_path / "w"
    store: dict = {}
    monkeypatch.setattr(orch_mod, "make_role_agents", _recording_factory(store))
    assert run(wd, "--workflow", "existing", "--debate-rounds", "0") == 0
    rd = only_run(wd)
    assert file_names(rd)[0] == "01_explore_scout.md"
    agents = store["rounds"][0]
    assert agents["scout"].calls[0].step == "explore" and agents["scout"].calls[0].mode is Mode.READ
    assert "## 사전 조사" in agents["claude"].calls[0].prompt          # propose
    assert "mock-scout 사전 조사" in agents["claude"].calls[0].prompt
    impl = next(c for c in agents["claude"].calls if c.step == "implement")
    assert "## 사전 조사" in impl.prompt
    assert "## 사전 조사" not in agents["codex"].calls[-1].prompt     # review
    assert RunState.load(rd).explores == {"explore": "01_explore_scout.md"}


def test_lean_single_proposer(tmp_path: Path):
    wd = tmp_path / "w"
    assert run(wd, "--workflow", "lean", "--debate-rounds", "3") == 0
    rd = only_run(wd)
    st = RunState.load(rd)
    assert st.config["debate_rounds"] == 0
    assert file_names(rd)[:2] == ["01_propose_claude.md", "02_impl1_claude.md"]
    assert (wd / "DESIGN.md").read_text(encoding="utf-8") == Transcript(rd).read("01_propose_claude.md")


def test_design_only_and_no_build(tmp_path: Path, capsys):
    wd = tmp_path / "w"
    assert run(wd, "--workflow", "lean", "--design-only") == 0
    assert RunState.load(only_run(wd)).status == DONE_DESIGN
    wd2 = tmp_path / "w2"
    write_project_wf(wd2, "scan", '[roles.s]\nagent = "codex"\n[[steps]]\nkind = "explore"\nrole = "s"\n')
    assert run(wd2, "--workflow", "scan") == 0
    assert RunState.load(only_run(wd2)).status == DONE_DESIGN
    assert run(wd2, "--workflow", "scan", "--design-only") == 2
    assert "설계(debate) 단계가 없어" in capsys.readouterr().err


def test_build_only_needs_design(tmp_path: Path, capsys):
    wd = tmp_path / "w"
    write_project_wf(wd, "b", '[roles.a]\nagent = "claude"\n[roles.b]\nagent = "codex"\n'
                              '[[steps]]\nkind = "build"\nimplementer = "a"\nreviewers = ["b"]\n')
    assert run(wd, "--workflow", "b") == 2
    assert "DESIGN.md" in capsys.readouterr().err


def test_cli_errors(tmp_path: Path, capsys):
    assert run(tmp_path / "a", "--workflow", "nope") == 2
    assert "찾을 수 없습니다" in capsys.readouterr().err
    assert run(tmp_path / "b", "--workflow", "secure", "--synth", "claude") == 2
    assert "classic 워크플로에서만" in capsys.readouterr().err
    assert run(tmp_path / "c", "--workflow", "Bad!") == 2


def test_template_params_and_cli_precedence(tmp_path: Path):
    text = ('[roles.a]\nagent = "claude"\n[roles.b]\nagent = "codex"\n'
            '[[steps]]\nkind = "debate"\nproposers = ["a", "b"]\nsynth = "a"\nrounds = 2\n'
            '[[steps]]\nkind = "build"\nimplementer = "a"\nreviewers = ["b"]\nmax_review = 1\n')
    wd = tmp_path / "w"
    write_project_wf(wd, "p", text)
    assert run(wd, "--workflow", "p") == 1
    c = RunState.load(only_run(wd)).config
    assert (c["debate_rounds"], c["max_review"]) == (2, 1)
    wd2 = tmp_path / "w2"
    write_project_wf(wd2, "p", text)
    assert run(wd2, "--workflow", "p", "--debate-rounds", "0", "--max-review", "2") == 0
    c = RunState.load(only_run(wd2)).config
    assert (c["debate_rounds"], c["max_review"]) == (0, 2)


def test_workflow_from_duet_toml(tmp_path: Path):
    wd = tmp_path / "w"
    wd.mkdir()
    (wd / "duet.toml").write_text('workflow = "lean"\n', encoding="utf-8")
    assert run(wd) == 0
    assert RunState.load(only_run(wd)).workflow["name"] == "lean"


def test_resume_uses_saved_workflow(tmp_path: Path, monkeypatch):
    wd = tmp_path / "w"
    write_project_wf(wd, "two", '[roles.dev]\nagent = "claude"\n[roles.r1]\nagent = "codex"\n[roles.r2]\nagent = "codex"\n'
                                '[[steps]]\nkind = "debate"\nproposers = ["dev"]\n'
                                '[[steps]]\nkind = "build"\nimplementer = "dev"\nreviewers = ["r1", "r2"]\n')
    store: dict = {}
    calls = {"n": 0}

    def factory(cfg, wf, *, mock):
        calls["n"] += 1
        per = {"r2": {"rate_limit_on_calls": {1}}} if calls["n"] == 1 else {}
        agents = {n: MockAdapter(label=n, approve_on_review=1, **per.get(n, {})) for n in wf.used_roles()}
        store.setdefault("rounds", []).append(agents)
        return agents

    monkeypatch.setattr(orch_mod, "make_role_agents", factory)
    assert run(wd, "--workflow", "two") == 3
    rd = only_run(wd)
    st = RunState.load(rd)
    assert st.status == STOPPED_RATE_LIMIT and st.is_done("review:1:r1") and not st.is_done("review:1")
    (wd / ".duet" / "workflows" / "two.toml").unlink()            # 파일이 없어도 저장본으로 이어간다
    assert main(["resume", "--workdir", str(wd)]) == 0
    st = RunState.load(rd)
    assert st.status == DONE_APPROVED and st.review_history[0]["approved"]
    second = store["rounds"][1]
    assert second["r1"].calls == [] and [c.step for c in second["r2"].calls] == ["review"]   # r1 은 다시 안 부름


def test_resume_unapproved_continues_build(tmp_path: Path, monkeypatch):
    wd = tmp_path / "w"
    assert run(wd, "--workflow", "lean", "--max-review", "1") == 1
    rd = only_run(wd)
    st = RunState.load(rd)
    assert st.status == DONE_UNAPPROVED and st.is_done("build")
    assert main(["resume", "--workdir", str(wd), "--max-review", "3"]) == 0
    assert RunState.load(rd).status == DONE_APPROVED


def test_workflows_command(tmp_path: Path, capsys):
    assert main(["workflows"]) == 0
    out = capsys.readouterr().out
    assert "classic" in out and "secure" in out and "[내장]" in out
    assert main(["workflows", "show", "secure"]) == 0
    out = capsys.readouterr().out
    assert "security" in out and "templates" not in out and "템플릿 review=review_security" in out
    assert main(["workflows", "show"]) == 2


def test_log_shows_roles(tmp_path: Path, capsys):
    wd = tmp_path / "w"
    assert run(wd, "--workflow", "secure", "--debate-rounds", "0") == 0
    capsys.readouterr()
    assert main(["log", "--workdir", str(wd)]) == 0
    out = capsys.readouterr().out
    assert "워크플로: secure" in out and "security(codex)" in out


def test_state_ignores_unknown_call_fields():
    st = RunState.from_dict({"run_id": "r", "task": "t",
                             "calls": [{"agent": "claude", "step": "propose", "sec": 1, "exit": 0, "future": 1}]})
    assert st.calls[0].agent == "claude"


# ====================================================================== UI
def test_ui_workflows_and_run(server, tmp_path: Path):  # noqa: F811
    s, d, _ = call(server, "GET", "/api/workflows")
    assert s == 200 and d["default"] == "classic"
    ids = {w["id"]: w for w in d["workflows"]}
    assert "secure" in ids and ids["secure"]["roles"][2]["templates"] == {"review": "review_security"}
    wd = tmp_path / "ui"
    s, job, _ = call(server, "POST", "/api/actions/run",
                     body={"project": str(wd), "task": "t", "mock": True, "workflow": "lean"})
    assert s == 200, job
    j = wait_for(lambda: (lambda x: x if not x["running"] else None)(_job(server, job["id"])))
    assert j["returncode"] == 0, j["log_tail"]
    st = RunState.load(list_run_dirs(wd)[-1])
    assert st.workflow["name"] == "lean"
    s, body, _ = call(server, "POST", "/api/actions/run",
                      body={"project": str(tmp_path / "ui2"), "task": "t", "mock": True, "workflow": "nope"})
    assert s == 400 and "찾을 수 없습니다" in body["error"]


def test_ui_current_call_maps_role_to_cli(server, tmp_path: Path):  # noqa: F811
    rd = tmp_path / "run"
    rd.mkdir()
    wf = parse(wf_data(DEBATE, BUILD, roles={"a": {"agent": "claude"}, "b": {"agent": "codex"},
                                             "c": {"agent": "codex"}}))
    RunState(run_id="r", task="t", workflow=wf.to_dict()).save(rd)
    (rd / "console.log").write_text("[10:00:00] b ← review 실행 중...\n", encoding="utf-8")
    c = server.dashboard._current_call(rd)
    assert c["agent"] == "b" and c["cli"] == "codex"
