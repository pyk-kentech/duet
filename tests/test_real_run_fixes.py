"""실제 실행(secure·existing)에서 찾은 문제 4건의 수정 (DESIGN.md 19.5~19.7, 19.2 audit)."""

from __future__ import annotations

from pathlib import Path

import pytest

import duet.orchestrator as orch_mod
from duet.agents.mock import MockAdapter
from duet.cli import main
from duet.state import DONE_APPROVED, DONE_DESIGN, RunState, list_run_dirs
from duet.testing import resolve_command
from duet.workflow import WorkflowError, load_workflow, parse_workflow
from duet.config import Config
from duet.workspace import Workspace
from tests.test_ui import call, server  # noqa: F401 - pytest 픽스처

ORIGINAL_DESIGN = "# 프로젝트 전체 설계\n- 모듈 A, B\n"


def only_run(wd: Path) -> Path:
    [rd] = list_run_dirs(wd)
    return rd


def existing_project(tmp_path: Path) -> Path:
    """DESIGN.md 와 코드가 이미 커밋된 기존 프로젝트."""
    wd = tmp_path / "proj"
    wd.mkdir()
    (wd / "DESIGN.md").write_text(ORIGINAL_DESIGN, encoding="utf-8")
    (wd / "main.py").write_text("print('old')\n", encoding="utf-8")
    ws = Workspace(wd)
    ws.ensure_repo()
    ws.commit_all("init")
    return wd


def recording(store: dict, **per_role):
    def factory(cfg, wf, *, mock):
        agents = {n: MockAdapter(label=n, **per_role.get(n, {})) for n in wf.used_roles()}
        store.setdefault("rounds", []).append(agents)
        return agents
    return factory


# ====================================================================== 1. 변경 설계
class TestChangeDesign:
    def test_output_key(self):
        roles = {"a": {"agent": "claude"}, "b": {"agent": "codex"}}
        wf = parse_workflow({"roles": roles, "steps": [
            {"kind": "debate", "proposers": ["a", "b"], "synth": "b", "output": "change"}]},
            name_hint="t", source="file", where="t")
        assert wf.steps[0].output == "change" and "변경 설계" in wf.summary()
        assert wf.steps[0].to_dict()["output"] == "change"
        wf = parse_workflow({"roles": roles, "steps": [{"kind": "debate", "proposers": ["a"], "output": "design"}]},
                            name_hint="t", source="file", where="t")
        assert wf.steps[0].output is None and "output" not in wf.steps[0].to_dict()
        with pytest.raises(WorkflowError, match="output"):
            parse_workflow({"roles": roles, "steps": [{"kind": "debate", "proposers": ["a"], "output": "x"}]},
                           name_hint="t", source="file", where="t")
        assert load_workflow("existing", None, Config()).first("debate").output == "change"

    def test_existing_keeps_design_md(self, tmp_path: Path, monkeypatch):
        wd = existing_project(tmp_path)
        store: dict = {}
        monkeypatch.setattr(orch_mod, "make_role_agents", recording(store))
        assert main(["run", "-L 옵션 추가", "--workdir", str(wd), "--mock", "--workflow", "existing",
                     "--debate-rounds", "0"]) == 0
        rd = only_run(wd)
        st = RunState.load(rd)
        doc = f"docs/changes/{rd.name}.md"
        assert st.status == DONE_APPROVED and st.design_doc == doc
        assert (wd / "DESIGN.md").read_text(encoding="utf-8") == ORIGINAL_DESIGN   # 그대로
        assert "최종 설계" in (wd / doc).read_text(encoding="utf-8")                # 종합 결과
        assert not (rd / "DESIGN.prev.md").exists()
        ws = Workspace(wd)
        assert doc in ws.git("show", "--name-only", "--format=", ws.git("log", "--format=%h", "--grep=^duet: design$").strip())
        agents = store["rounds"][0]
        propose = agents["claude"].calls[0].prompt
        assert "## 기존 프로젝트의 변경" in propose and doc in propose
        impl = next(c for c in agents["claude"].calls if c.step == "implement").prompt
        assert f"현재 디렉터리의 {doc}를 읽고" in impl and "기존 프로젝트를 바꾸는 것이다" in impl
        assert f"- {doc}는 수정하지 마라." in impl and "DESIGN.md는 수정하지 마라" not in impl
        review = next(c for c in agents["codex"].calls if c.step == "review").prompt
        assert f"설계 문서는 {doc}" in review and f"설계({doc}) 위반" in review
        assert "## 기존 프로젝트의 변경" not in review
        fix = next(c for c in agents["claude"].calls if c.step == "fix").prompt
        assert f"{doc}와 .duet/ 디렉터리는 수정하지 마라." in fix

    def test_review_diff_excludes_change_doc_but_shows_design_md(self, tmp_path: Path, monkeypatch):
        wd = existing_project(tmp_path)
        store: dict = {}

        def impl(req, n):
            if req.step == "implement":
                (Path(req.cwd) / "DESIGN.md").write_text(ORIGINAL_DESIGN + "- -L 옵션\n", encoding="utf-8")
                (Path(req.cwd) / "main.py").write_text("print('new')\n", encoding="utf-8")
            return "done\n"

        def factory(cfg, wf, *, mock):
            agents = {n: MockAdapter(label=n, approve_on_review=1) for n in wf.used_roles()}
            agents["claude"] = MockAdapter(label="claude", responder=lambda r, n: (
                impl(r, n) if r.step == "implement" else MockAdapter(label="c")._default_response(r)))
            store["agents"] = agents
            return agents

        monkeypatch.setattr(orch_mod, "make_role_agents", factory)
        assert main(["run", "t", "--workdir", str(wd), "--mock", "--workflow", "existing", "--debate-rounds", "0"]) == 0
        review = next(c for c in store["agents"]["codex"].calls if c.step == "review").prompt
        diff = review.split("[구현 전체 diff]")[1].split("[바뀐 함수가 쓰이는 곳]")[0]
        assert "DESIGN.md" in diff and "main.py" in diff     # 프로젝트 문서 갱신은 리뷰 대상
        assert "docs/changes/" not in diff

    def test_design_only_and_ui_design_tab(self, server, tmp_path: Path, capsys):  # noqa: F811
        wd = existing_project(tmp_path)
        assert main(["run", "t", "--workdir", str(wd), "--mock", "--workflow", "existing", "--design-only"]) == 0
        rd = only_run(wd)
        st = RunState.load(rd)
        assert st.status == DONE_DESIGN
        assert f"{wd / st.design_doc} 를 확인하세요" in capsys.readouterr().out
        server.dashboard.registry.add(wd)
        s, d, _ = call(server, "GET", f"/api/design?project={wd}&run={rd.name}")
        assert s == 200 and d["path"].endswith(st.design_doc) and "최종 설계" in d["text"]
        s, d, _ = call(server, "GET", f"/api/design?project={wd}")
        assert d["text"] == ORIGINAL_DESIGN

    def test_skip_design_keeps_design_md(self, tmp_path: Path):
        wd = existing_project(tmp_path)
        assert main(["run", "t", "--workdir", str(wd), "--mock", "--workflow", "existing", "--skip-design"]) == 0
        assert RunState.load(only_run(wd)).design_doc is None

    def test_classic_unchanged(self, tmp_path: Path):
        wd = tmp_path / "w"
        assert main(["run", "t", "--workdir", str(wd), "--mock", "--debate-rounds", "0"]) == 0
        assert RunState.load(only_run(wd)).design_doc is None
        assert (wd / "DESIGN.md").is_file() and not (wd / "docs").exists()


# ====================================================================== 2. 감사 문구
def test_audit_log_is_advisory(tmp_path: Path, monkeypatch, capsys):
    p3_audit = ("## 반드시 고칠 것\n(없음)\n## 고치면 좋은 것 (P3)\n- [P3] a\n\n"
                "<verdict>\nstatus: APPROVED\nmust_fix: 0\np1: 0\np2: 0\np3: 2\n</verdict>\n")

    def factory(cfg, wf, *, mock):
        agents = {n: MockAdapter(label=n, approve_on_review=1) for n in wf.used_roles()}
        agents["auditor"] = MockAdapter(label="auditor", responder=lambda r, n: p3_audit)
        return agents

    monkeypatch.setattr(orch_mod, "make_role_agents", factory)
    wd = tmp_path / "w"
    assert main(["run", "t", "--workdir", str(wd), "--mock", "--workflow", "secure", "--debate-rounds", "0",
                 "--block-severity", "P3"]) == 0
    out = capsys.readouterr().out
    line = next(ln for ln in out.splitlines() if "감사 결과(auditor)" in ln)
    assert "확인 필요 — P1=0 P2=0 P3=2 (참고용)" in line and "반려" not in line
    assert RunState.load(only_run(wd)).status == DONE_APPROVED


# ====================================================================== 3. 명령 실행 가능 여부
def test_claude_reviewer_told_it_cannot_run(tmp_path: Path, monkeypatch):
    seen: dict = {}

    def factory(cfg, *, mock):
        seen["claude"] = MockAdapter(label="claude", approve_on_review=1)
        seen["codex"] = MockAdapter(label="codex")
        return dict(seen)

    monkeypatch.setattr(orch_mod, "make_agents", factory)
    wd = tmp_path / "w"
    assert main(["run", "t", "--workdir", str(wd), "--mock", "--debate-rounds", "0",
                 "--implementer", "codex", "--reviewer", "claude"]) == 0
    review = next(c for c in seen["claude"].calls if c.step == "review").prompt
    assert "명령을 실행할 수 없다" in review and "좁게 실행해라" not in review and "재현 테스트로 내라" in review


def test_codex_reviewer_and_claude_with_bash(tmp_path: Path, monkeypatch):
    seen: dict = {}

    def factory(cfg, *, mock):
        seen["claude"] = MockAdapter(label="claude")
        seen["codex"] = MockAdapter(label="codex", approve_on_review=1)
        return dict(seen)

    monkeypatch.setattr(orch_mod, "make_agents", factory)
    wd = tmp_path / "w"
    wd.mkdir()
    (wd / "duet.toml").write_text('test_command = "true"\n', encoding="utf-8")
    assert main(["run", "t", "--workdir", str(wd), "--mock", "--debate-rounds", "0"]) == 0
    review = next(c for c in seen["codex"].calls if c.step == "review").prompt
    assert "좁게 실행해라" in review and "명령을 실행할 수 없다" not in review

    from tests.helpers import make_ctx

    ctx = make_ctx(tmp_path / "x", overrides={"claude": {"read_args": ["--allowedTools", "Read,Glob,Grep,Bash"]}})
    assert ctx.can_run_commands("claude") and ctx.can_run_commands("codex")
    assert not make_ctx(tmp_path / "y").can_run_commands("claude")


def test_audit_run_instruction_by_cli(tmp_path: Path, monkeypatch):
    store: dict = {}
    monkeypatch.setattr(orch_mod, "make_role_agents", recording(store, codex={"approve_on_review": 1},
                                                                security={"approve_on_review": 1}))
    wd = tmp_path / "w"
    assert main(["run", "t", "--workdir", str(wd), "--mock", "--workflow", "secure", "--debate-rounds", "0"]) == 0
    audit = store["rounds"][0]["auditor"].calls[0].prompt   # auditor 는 claude
    assert "명령을 실행할 수 없다" in audit and "{run_instruction}" not in audit


# ====================================================================== 4. 테스트 명령 출처
def test_test_command_source_label(tmp_path: Path):
    (tmp_path / "duet.toml").write_text('test_command = "uvx pytest -q"\n', encoding="utf-8")
    assert resolve_command(tmp_path, "uvx pytest -q") == ("uvx pytest -q", "duet.toml")
    assert resolve_command(tmp_path, "pytest -x") == ("pytest -x", "설정")
    assert resolve_command(tmp_path, "auto") == ("uvx pytest -q", "duet.toml")
    assert resolve_command(tmp_path / "none", "pytest -x") == ("pytest -x", "설정")
