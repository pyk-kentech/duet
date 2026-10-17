"""M23: 관리자·작업자 분업 — extended 워크플로 (DESIGN.md 29장)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import duet.orchestrator as orch_mod
from duet import team
from duet.agents.mock import MockAdapter
from duet.cli import main
from duet.config import Config
from duet.state import RunState, list_run_dirs
from duet.workflow import Workflow, WorkflowError, describe, list_workflows, load_workflow, parse_workflow
from duet.workspace import Workspace
from tests.helpers import file_names


def pkg(pid, files, deps=(), title=None):
    return {"id": pid, "title": title or pid, "files": list(files), "goal": "g", "interfaces": f"{pid}()",
            "depends_on": list(deps)}


# ====================================================================== 계획 검증 (29.2)
def test_validate_orders_by_dependencies():
    plan = team.validate({"packages": [pkg("P1", ["app/cli.py"], ["P2"]), pkg("P2", ["app/core/"]),
                                       pkg("P3", ["tests/"], ["P1"])], "shared": "x"})
    assert plan["order"] == ["P2", "P1", "P3"] and plan["shared"] == "x"


@pytest.mark.parametrize("packages,msg", [
    ([pkg("P1", ["a.py"]), pkg("P2", ["a.py"])], "겹칩니다"),
    ([pkg("P1", ["src/"]), pkg("P2", ["src/x.py"])], "겹칩니다"),
    ([pkg("P1", ["../x.py"])], "쓸 수 없는"),
    ([pkg("P1", ["/etc/x"])], "상대 경로"),
    ([pkg("P1", [".duet/x"])], "쓸 수 없는"),
    ([pkg("P1", [])], "비었습니다"),
    ([pkg("P1", ["a.py"], ["P2"]), pkg("P2", ["b.py"], ["P1"])], "순환"),
    ([pkg("P1", ["a.py"], ["P9"])], "없는 묶음"),
    ([pkg("P1", ["a.py"]), pkg("P1", ["b.py"])], "겹칩니다"),
    ([], "1~12"),
])
def test_validate_rejects(packages, msg):
    with pytest.raises(team.PlanError, match=msg):
        team.validate({"packages": packages, "shared": ""})


def test_owner_and_outside():
    plan = team.validate({"packages": [pkg("P1", ["pkg/core.py"]), pkg("P2", ["tests/"])], "shared": ""})
    assert team.owner_of(plan, "pkg/core.py:12") == "P1" and team.owner_of(plan, "`tests/test_a.py`") == "P2"
    assert team.owner_of(plan, "README.md") is None and team.owner_of(plan, "") is None
    p1 = team.package(plan, "P1")
    assert team.outside(p1, ["pkg/core.py", "IMPLEMENTATION_NOTES.md", "tests/test_a.py"]) == ["tests/test_a.py"]
    fb = team.fallback_plan("x")
    assert team.outside(team.package(fb, "P1"), ["anything.py"]) == [] and fb["fallback"] == "x"


def test_schema_strict():
    it = team.PLAN_SCHEMA["properties"]["packages"]["items"]
    assert it["additionalProperties"] is False and set(it["required"]) == set(it["properties"])


def test_revert_paths(tmp_path: Path):
    ws = Workspace(tmp_path / "r")
    ws.ensure_repo()
    (ws.workdir / "keep.py").write_text("v1\n", encoding="utf-8")
    ws.commit_all("base")
    (ws.workdir / "keep.py").write_text("v2\n", encoding="utf-8")
    (ws.workdir / "new.py").write_text("x\n", encoding="utf-8")
    ws.revert_paths(["keep.py", "new.py"])
    assert (ws.workdir / "keep.py").read_text(encoding="utf-8") == "v1\n" and not (ws.workdir / "new.py").exists()


# ====================================================================== 워크플로 정의 (29.1)
ROLES = {"m": {"agent": "codex"}, "w": {"agent": "claude"}, "r": {"agent": "codex"}}


def parse(build):
    return parse_workflow({"roles": ROLES, "steps": [{"kind": "build", **build}]}, name_hint="t", source="file", where="t")


def test_parse_manager_workers():
    wf = parse({"manager": "m", "workers": ["w"], "reviewers": ["r"]})
    st = wf.steps[0]
    assert st.manager == "m" and st.workers == ["w"] and st.lead == "m" and st.implementer is None
    assert set(wf.used_roles()) == {"m", "w", "r"} and "관리자 m → 작업자 w" in wf.summary()
    again = Workflow.from_dict(wf.to_dict())                                     # run.json 에서 다시 읽기
    assert again.steps[0].manager == "m"
    for bad, msg in [({"implementer": "w", "manager": "m", "workers": ["w"], "reviewers": ["r"]}, "함께"),
                     ({"manager": "m", "workers": ["m"], "reviewers": ["r"]}, "작업자가 될 수 없"),
                     ({"manager": "m", "workers": ["w"], "reviewers": ["w"]}, "리뷰어가 될 수 없"),
                     ({"manager": "m", "workers": ["w"], "reviewers": ["r"], "arbiter": "m"}, "중재자가 될 수 없")]:
        with pytest.raises(WorkflowError, match=msg):
            parse(bad)


def test_builtin_extended():
    wf = load_workflow("extended", None, Config())
    build = wf.first("build")
    assert build.manager == "manager" and build.workers == ["worker"]
    assert wf.roles["manager"].agent == "codex" and wf.roles["manager"].effort == "high"
    assert wf.roles["worker"].model == "claude-sonnet-5-5" and wf.roles["worker"].effort == "medium"
    assert "extended" in [w["id"] for w in list_workflows(None)]
    d = describe(wf)
    assert d["steps"][1]["manager"] == "manager" and d["steps"][1]["workers"] == ["worker"]


# ====================================================================== build 통합
def run(tmp_path, monkeypatch, *extra, overrides=None, wf="extended"):
    store: dict = {}

    def factory(cfg, w, *, mock):
        agents = {n: MockAdapter(label=n) for n in w.used_roles()}
        agents.update(overrides or {})
        store["a"] = agents
        return agents

    monkeypatch.setattr(orch_mod, "make_role_agents", factory)
    wd = tmp_path / "w"
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "duet.toml").write_text('test_command = "none"\n', encoding="utf-8")
    rc = main(["run", "t", "--workdir", str(wd), "--mock", "--workflow", wf, "--debate-rounds", "0", *extra])
    [rd] = list_run_dirs(wd)
    return rc, store["a"], RunState.load(rd), rd, wd


def test_extended_end_to_end_with_fix_routing(tmp_path, monkeypatch):
    rc, a, st, rd, wd = run(tmp_path, monkeypatch)
    assert rc == 0 and st.status == "done_approved" and st.team["order"] == ["P1", "P2"]
    names = file_names(rd)
    for frag in ("_plan1_manager.md", "_part_P1_worker.md", "_part_P2_worker.md", "_integrate1_manager.md",
                 "_fix2_worker_P1.md"):
        assert any(n.endswith(frag) for n in names), (frag, names)
    assert [c.step for c in a["manager"].calls] == ["plan", "integrate"]      # 2라운드 지적(main.py)은 P1 작업자에게
    assert [c.step for c in a["worker"].calls] == ["part", "part", "fix"]
    fix = a["worker"].calls[-1]
    assert "이번에 네가 고칠 지적: I1 (묶음 P1, 맡은 파일: main.py)" in fix.prompt
    assert st.team["routes"]["2"]["worker:P1"]["ids"] == ["I1"]
    part2 = a["worker"].calls[1].prompt
    assert "[맡은 파일]\n- tests/" in part2 and "- P1 본체" in part2 and "main()" in part2   # 다른 묶음 인터페이스
    log = Workspace(wd).git("log", "--format=%s")
    assert "duet: part P1" in log and "duet: part P2" in log and "duet: impl round 1" in log
    assert (wd / "tests" / "test_part.py").exists()


def test_worker_outside_files_reverted(tmp_path, monkeypatch):
    def sneaky(req, n):
        if req.step == "part" and "[맡은 파일]\n- tests/" in req.prompt:
            (Path(req.cwd) / "tests").mkdir(exist_ok=True)
            (Path(req.cwd) / "tests" / "test_x.py").write_text("ok\n", encoding="utf-8")
            (Path(req.cwd) / "main.py").write_text("hacked\n", encoding="utf-8")      # P1 의 파일
            return "done"
        return MockAdapter(label="worker")._default_response(req)

    rc, a, st, rd, wd = run(tmp_path, monkeypatch, overrides={"worker": MockAdapter(label="worker", responder=sneaky)})
    p2 = st.team["parts"]["P2"]
    assert p2["reverted"] == ["main.py"] and p2["changed"] == ["tests/test_x.py"]
    assert Workspace(wd).git("show", f"{p2['commit']}:main.py").strip() != "hacked"


def test_unreadable_plan_falls_back(tmp_path, monkeypatch, capsys):
    mgr = MockAdapter(label="manager", responder=lambda req, n: "계획 대신 잡담" if req.step == "plan"
                      else MockAdapter(label="manager")._default_response(req))
    rc, a, st, rd, wd = run(tmp_path, monkeypatch, overrides={"manager": mgr})
    assert rc == 0 and st.team["fallback"] and st.team["order"] == ["P1"]
    assert [c.step for c in a["worker"].calls][:1] == ["part"]
    assert "묶음 하나로 진행합니다" in capsys.readouterr().out


def test_resume_continues_from_next_package(tmp_path, monkeypatch):
    worker = MockAdapter(label="worker", rate_limit_on_calls={2})            # 두 번째 묶음에서 한도
    rc, a, st, rd, wd = run(tmp_path, monkeypatch, overrides={"worker": worker})
    assert st.status == "stopped_rate_limit" and "part:P1" in st.done and "part:P2" not in st.done
    store: dict = {}

    def factory(cfg, w, *, mock):
        store["a"] = {n: MockAdapter(label=n) for n in w.used_roles()}
        return store["a"]

    monkeypatch.setattr(orch_mod, "make_role_agents", factory)
    assert main(["resume", "--workdir", str(wd)]) == 0
    assert [c.step for c in store["a"]["worker"].calls][:1] == ["part"]          # P2 만 다시
    assert "[맡은 파일]\n- tests/" in store["a"]["worker"].calls[0].prompt
    assert [c.step for c in store["a"]["manager"].calls][:1] == ["integrate"]  # 분해는 다시 안 함
