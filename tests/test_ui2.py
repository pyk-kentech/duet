"""화면 2차 (DESIGN.md 36.21): 작업대의 목록 API."""

from __future__ import annotations

from pathlib import Path

from tenure import worktree
from tenure.events import EventLog, STEP_START
from tenure.registry import Registry
from tenure.state import DONE_APPROVED, RUNNING, RunState, create_run_dir
from tenure.ui.dashboard import Dashboard, dispatch


def make_run(wd: Path, rid: str, status: str, task: str = "할일 CLI\n자세히") -> Path:
    rd = create_run_dir(wd, rid)
    st = RunState(run_id=rid, task=task, config={"workflow": "quick"})
    st.status = status
    st.record_call("claude", "implement", 1.0, 0, usage={"input_tokens": 1200, "output_tokens": 30})
    st.save(rd)
    EventLog(rd).emit("state", status=status)       # 이벤트 기록이 있어야 M30 뒤의 실행 (없으면 본 것으로 침)
    return rd


def test_works_groups_counts_and_tokens(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    reg = Registry()
    reg.add(a)
    reg.add(b)
    make_run(a, "20261022-000001", DONE_APPROVED)
    rd2 = make_run(b, "20261022-000002", DONE_APPROVED)
    w = dispatch(Dashboard(), "works", {})
    names = [g["name"] for g in w["groups"]]
    assert set(names) == {"a", "b"}
    item = next(g for g in w["groups"] if g["name"] == "b")["items"][0]
    assert item["run_id"] == rd2.name and item["tokens"] == 1200 and item["race"] is False
    assert item["activity"]["state"] == "done-unseen" and w["counts"]["done-unseen"] == 2
    assert "doing" not in item                                        # 진행 중이 아니면 '지금 하는 일' 없음


def test_works_live_doing_and_hides_discarded_and_bench(tmp_path, monkeypatch):
    wd = tmp_path / "p"
    wd.mkdir()
    Registry().add(wd)
    rd = make_run(wd, "20261022-000003", RUNNING)
    EventLog(rd).emit(STEP_START, agent="claude", role="claude", step="fix", round=2)
    d = Dashboard()
    monkeypatch.setattr(Dashboard, "_run_live", lambda self, r: {"pid": 1, "run_id": r.name})
    item = d.works()["groups"][0]["items"][0]
    assert item["live"] and item["doing"]["step"] == "fix" and item["doing"]["round"] == 2
    # 버린 worktree 실행은 목록에서 뺀다
    monkeypatch.setattr(Dashboard, "_tree", lambda self, project, rid: worktree.Tree(
        run_id=rid, path=str(wd), branch="b", base_branch="main", base_commit="x", created="", status=worktree.DISCARDED))
    st = RunState.load(rd)
    st.worktree = {"project": str(wd)}
    st.save(rd)
    assert d.works()["groups"][0]["items"] == []
