from pathlib import Path

import pytest

from duet.agents.mock import MockAdapter
from duet.phases.build import BuildPhase, truncate_diff
from duet.phases.common import AgentFailed
from duet.state import DONE_APPROVED, DONE_UNAPPROVED, FAILED, RUNNING, RunState
from duet.workspace import Workspace
from tests.helpers import file_names, make_ctx


def prepare(tmp_path: Path, agents=None, **overrides):
    ctx = make_ctx(tmp_path, agents=agents, overrides=overrides)
    (tmp_path / "DESIGN.md").write_text("# 설계\n- main.py 하나\n", encoding="utf-8")
    return ctx


def test_approved_on_second_review(tmp_path: Path):
    agents = {"claude": MockAdapter(label="claude"), "codex": MockAdapter(label="codex", approve_on_review=2)}
    ctx = prepare(tmp_path, agents, max_review=3)
    assert BuildPhase(ctx).run() is True
    st = ctx.state
    assert st.status == DONE_APPROVED and st.last_verdict == "APPROVED"
    assert file_names(ctx.run_dir) == ["01_impl1_claude.md", "02_review1_codex.md",
                                       "03_impl2_claude.md", "04_review2_codex.md"]
    ws = Workspace(tmp_path)
    assert ws.commit_count() == 3  # design + impl1 + impl2
    assert not ws.dirty()
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()[0] == ".duet/"
    assert (tmp_path / "main.py").read_text(encoding="utf-8") == "print('hi')\n# fix\n"
    assert [c.step for c in agents["claude"].calls] == ["implement", "fix"]
    assert [c.step for c in agents["codex"].calls] == ["review", "review"]
    assert st.is_done("build:base") and st.is_done("review:2") and not st.is_done("impl:3")
    assert RunState.load(ctx.run_dir).status == DONE_APPROVED


def test_unapproved_after_max_review(tmp_path: Path):
    agents = {"claude": MockAdapter(label="claude"), "codex": MockAdapter(label="codex", approve_on_review=0)}
    ctx = prepare(tmp_path, agents, max_review=2)
    assert BuildPhase(ctx).run() is False
    assert ctx.state.status == DONE_UNAPPROVED
    assert ctx.state.last_review == "04_review2_codex.md"
    assert Workspace(tmp_path).commit_count() == 3
    assert any("판정: CHANGES_REQUESTED" in m for m in ctx.logs)


def test_roles_swapped(tmp_path: Path):
    agents = {"claude": MockAdapter(label="claude", approve_on_review=1), "codex": MockAdapter(label="codex")}
    ctx = prepare(tmp_path, agents, implementer="codex", reviewer="claude", max_review=2)
    assert BuildPhase(ctx).run() is True
    assert file_names(ctx.run_dir) == ["01_impl1_codex.md", "02_review1_claude.md"]


def test_fix_prompt_contains_previous_review(tmp_path: Path):
    prompts = []

    def impl(req, n):
        prompts.append(req.prompt)
        (req.cwd / "main.py").write_text(f"v{n}\n", encoding="utf-8")
        return "done"

    def rev(req, n):
        prompts.append(req.prompt)
        if n == 1:
            return "## 반드시 고칠 것\n- 고유한지적#1\n<verdict>\nstatus: CHANGES_REQUESTED\nmust_fix: 1\n</verdict>"
        return "<verdict>\nstatus: APPROVED\nmust_fix: 0\n</verdict>"

    agents = {"claude": MockAdapter(label="claude", responder=impl), "codex": MockAdapter(label="codex", responder=rev)}
    ctx = prepare(tmp_path, agents)
    assert BuildPhase(ctx).run()
    implement_p, review1_p, fix_p, review2_p = prompts
    assert "DESIGN.md를 읽고" in implement_p and "[리뷰]" not in implement_p
    assert "고유한지적#1" in fix_p and "리뷰어(codex)" in fix_p
    assert "+v1" in review1_p and "구현자(claude)" in review1_p
    # 2라운드는 지난 리뷰 이후 바뀐 부분만 (v1 → v2), 파일 요약은 처음부터 기준
    assert "[지난 리뷰 이후 바뀐 부분 (diff)]" in review2_p and "-v1" in review2_p and "+v2" in review2_p
    assert "[처음부터의 변경 파일 요약]" in review2_p


def test_full_review_diff_mode(tmp_path: Path):
    prompts = []

    def impl(req, n):
        (req.cwd / "main.py").write_text(f"v{n}\n", encoding="utf-8")
        return "done"

    def rev(req, n):
        prompts.append(req.prompt)
        return "<verdict>\nstatus: CHANGES_REQUESTED\nmust_fix: 1\n</verdict>" if n == 1 else "<verdict>\nstatus: APPROVED\nmust_fix: 0\n</verdict>"

    agents = {"claude": MockAdapter(label="claude", responder=impl), "codex": MockAdapter(label="codex", responder=rev)}
    ctx = prepare(tmp_path, agents, review_diff="full")
    assert BuildPhase(ctx).run()
    assert "[구현 전체 diff]" in prompts[1] and "+v2" in prompts[1] and "-v1" not in prompts[1]


def test_reviewer_changes_are_reverted(tmp_path: Path):
    def rev(req, n):
        (req.cwd / "main.py").write_text("tampered\n", encoding="utf-8")
        (req.cwd / "extra.txt").write_text("x", encoding="utf-8")
        return "<verdict>\nstatus: APPROVED\nmust_fix: 0\n</verdict>"

    agents = {"claude": MockAdapter(label="claude"), "codex": MockAdapter(label="codex", responder=rev)}
    ctx = prepare(tmp_path, agents)
    assert BuildPhase(ctx).run()
    assert (tmp_path / "main.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert not (tmp_path / "extra.txt").exists()
    assert not Workspace(tmp_path).dirty()
    assert any("경고: 리뷰어가 파일을 변경함" in m and "main.py" in m for m in ctx.logs)
    # 기록(.duet)은 살아 있다
    assert len(file_names(ctx.run_dir)) == 2


def test_diff_truncation(tmp_path: Path):
    seen = {}

    def impl(req, n):
        (req.cwd / "big.txt").write_text("x" * 5000 + "\n", encoding="utf-8")
        return "ok"

    def rev(req, n):
        seen["diff"] = req.prompt
        return "<verdict>\nstatus: APPROVED\nmust_fix: 0\n</verdict>"

    agents = {"claude": MockAdapter(label="claude", responder=impl), "codex": MockAdapter(label="codex", responder=rev)}
    ctx = prepare(tmp_path, agents, max_diff_chars=300)
    BuildPhase(ctx).run()
    assert "diff가 길어 잘림" in seen["diff"]
    assert "x" * 1000 not in seen["diff"]


def test_truncate_diff_helper():
    assert truncate_diff("", 10) == "(변경 없음)"
    assert truncate_diff("abc", 10) == "abc"
    assert truncate_diff("a" * 20, 10).startswith("a" * 10 + "\n... ")


def test_verdict_parse_failure_counts_as_changes_requested(tmp_path: Path):
    agents = {"claude": MockAdapter(label="claude"),
              "codex": MockAdapter(label="codex", responder=lambda r, n: "판정 없음")}
    ctx = prepare(tmp_path, agents, max_review=1)
    assert BuildPhase(ctx).run() is False
    assert any("판정 블록 없음" in m for m in ctx.logs)


def test_resume_after_failed_review(tmp_path: Path):
    # 2번째 호출(= 첫 리뷰)이 두 번 연속 실패
    agents = {"claude": MockAdapter(label="claude"),
              "codex": MockAdapter(label="codex", fail_on_calls={1, 2}, approve_on_review=1)}
    ctx = prepare(tmp_path, agents, max_review=2)
    with pytest.raises(AgentFailed):
        BuildPhase(ctx).run()
    st = ctx.state
    assert st.status == FAILED and st.is_done("impl:1") and not st.is_done("review:1")
    assert Workspace(tmp_path).commit_count() == 2

    st2 = RunState.load(ctx.run_dir)
    st2.status = RUNNING
    agents2 = {"claude": MockAdapter(label="claude"), "codex": MockAdapter(label="codex", approve_on_review=1)}
    ctx2 = make_ctx(tmp_path, agents=agents2, overrides={"max_review": 2, "timeout_sec": 5}, state=st2)
    assert BuildPhase(ctx2).run() is True
    assert agents2["claude"].calls == []           # 구현은 다시 하지 않음
    assert [c.step for c in agents2["codex"].calls] == ["review"]
    assert Workspace(tmp_path).commit_count() == 2  # 추가 커밋 없음
    assert file_names(ctx2.run_dir)[-1] == "04_review1_codex.md"
    assert st2.base_commit == st.base_commit
