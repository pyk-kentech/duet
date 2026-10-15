import json
from pathlib import Path

from duet.state import (
    DONE_APPROVED,
    RUN_JSON,
    RUNNING,
    STOPPED_RATE_LIMIT,
    CallRecord,
    RunState,
    create_run_dir,
    latest_run_dir,
    list_run_dirs,
    new_run_id,
)


def test_roundtrip(tmp_path: Path):
    st = RunState(run_id="20261014-174138", task="메모 CLI",
                  config={"implementer": "claude", "reviewer": "codex", "debate_rounds": 1})
    st.phase = "build"; st.step = "review"; st.round = 2; st.base_commit = "5da7bc7"
    st.proposals = {"claude": "01_propose_claude.md", "codex": "02_propose_codex.md"}
    st.critiques = ["03_r1_critique_claude.md"]
    st.last_review = "07_review1_codex.md"
    st.mark_done("propose:claude"); st.mark_done("propose:claude")
    st.record_call("claude", "propose", 41.26, 0, file="01_propose_claude.md")
    st.record_call("codex", "review", 3.0, 1, rate_limited=True)
    path = st.save(tmp_path)
    assert path.name == RUN_JSON and not (tmp_path / (RUN_JSON + ".tmp")).exists()
    assert st.updated_at

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["task"] == "메모 CLI" and raw["calls"][0] == {
        "agent": "claude", "step": "propose", "sec": 41.3, "exit": 0,
        "rate_limited": False, "timed_out": False, "file": "01_propose_claude.md", "usage": None}

    back = RunState.load(tmp_path)
    assert back == st
    assert back.done == ["propose:claude"]
    assert back.is_done("propose:claude") and not back.is_done("propose:codex")
    assert isinstance(back.calls[1], CallRecord) and back.calls[1].rate_limited


def test_unknown_keys_ignored_on_load(tmp_path: Path):
    (tmp_path / RUN_JSON).write_text(json.dumps({"run_id": "x", "task": "t", "future_field": 1}))
    st = RunState.load(tmp_path)
    assert st.run_id == "x" and st.status == RUNNING


def test_status_flags():
    st = RunState(run_id="x", task="t")
    assert st.resumable and not st.finished
    st.status = STOPPED_RATE_LIMIT
    assert st.resumable
    st.status = DONE_APPROVED
    assert st.finished and not st.resumable


def test_run_dirs(tmp_path: Path):
    assert latest_run_dir(tmp_path) is None
    d1 = create_run_dir(tmp_path, "20261014-000001")
    d2 = create_run_dir(tmp_path, "20261014-000002")
    d3 = create_run_dir(tmp_path, "20261014-000002")  # 충돌 → 접미사
    assert d3.name == "20261014-000002-2"
    assert d1.parent == tmp_path / ".duet" / "runs"
    # run.json 이 있는 것만 실행으로 친다
    assert list_run_dirs(tmp_path) == []
    RunState("a", "t").save(d1)
    RunState("b", "t").save(d2)
    assert [p.name for p in list_run_dirs(tmp_path)] == [d1.name, d2.name]
    assert latest_run_dir(tmp_path) == d2


def test_new_run_id_format():
    import datetime as dt
    assert new_run_id(dt.datetime(2026, 10, 14, 17, 41, 38)) == "20261014-174138"
