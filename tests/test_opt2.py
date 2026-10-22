"""최적화 2차 (DESIGN.md 36.18): 동시 에이전트 상한, 대시보드 읽기 캐시, 캐시 크기 상한."""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
from pathlib import Path

import pytest

from tenure import slots, usage
from tenure.agents.base import AgentResult, Mode
from tenure.config import ConfigError, load_config
from tenure.phases.common import PhaseContext
from tenure.registry import Registry
from tenure.state import DONE_APPROVED, RUNNING, RunState, create_run_dir
from tenure.transcript import Transcript
from tenure.ui.cache import RunDirs, StatCache
from tenure.ui.dashboard import Dashboard


# ------------------------------------------------------------------ slots
def test_resolve_auto_bounds(monkeypatch):
    assert slots.resolve(3) == 3
    monkeypatch.setattr(slots.os, "cpu_count", lambda: 64)
    assert slots.resolve(0) == slots.AUTO_MAX
    monkeypatch.setattr(slots.os, "cpu_count", lambda: 2)
    assert slots.resolve(0) == slots.AUTO_MIN


def test_slot_waits_until_free(tmp_path):
    logs: list[str] = []
    order: list[str] = []
    with slots.agent_slot(1, home=tmp_path) as i:
        assert i == 0 and slots.in_use(1, home=tmp_path) == 1

        def second():
            with slots.agent_slot(1, home=tmp_path, log=logs.append, poll=0.05):
                order.append("second")

        t = threading.Thread(target=second)
        t.start()
        time.sleep(0.3)
        assert order == [] and any("기다립니다" in x for x in logs)     # 자리가 없어 기다리는 중
        order.append("first-done")
    t.join(5)
    assert order == ["first-done", "second"] and any("자리가 나서" in x for x in logs)
    assert slots.in_use(1, home=tmp_path) == 0


def test_two_slots_run_together(tmp_path):
    with slots.agent_slot(2, home=tmp_path) as a, slots.agent_slot(2, home=tmp_path) as b:
        assert {a, b} == {0, 1} and slots.in_use(2, home=tmp_path) == 2


class SlotProbe:
    name = "probe"

    def __init__(self, home: Path):
        self.home, self.seen = home, None

    def ask(self, req):
        self.seen = slots.in_use(2, home=self.home)
        return AgentResult(text="ok", raw_stdout="", raw_stderr="", exit_code=0, duration_sec=0.0)


def test_call_holds_slot_while_agent_runs(tmp_path, isolated_tenure_home):
    rd = tmp_path / "run"
    rd.mkdir()
    st = RunState(run_id="r", task="t", config={})
    cfg = load_config(None, {"max_agents": 2})
    probe = SlotProbe(isolated_tenure_home)
    ctx = PhaseContext(task="t", workdir=tmp_path, cfg=cfg, agents={"claude": probe}, state=st,
                       transcript=Transcript(rd), run_dir=rd)
    ctx.call("claude", "implement", "p", Mode.WRITE, label="x")
    assert probe.seen == 1 and slots.in_use(2, home=isolated_tenure_home) == 0


def test_max_agents_validated():
    assert load_config(None, {"max_agents": 4}).max_agents == 4
    with pytest.raises(ConfigError, match="max_agents"):
        load_config(None, {"max_agents": 100})


# ------------------------------------------------------------------ caches
def test_stat_cache_reloads_on_change_and_evicts(tmp_path):
    f = tmp_path / "a.json"
    f.write_text("1", encoding="utf-8")
    calls = []
    c = StatCache(maxsize=2)
    load = lambda p: calls.append(p) or p.read_text(encoding="utf-8")     # noqa: E731
    assert c.get(f, load) == "1" and c.get(f, load) == "1" and len(calls) == 1
    f.write_text("22", encoding="utf-8")
    assert c.get(f, load) == "22" and len(calls) == 2
    for name in ("b", "c"):
        (tmp_path / name).write_text(name, encoding="utf-8")
        c.get(tmp_path / name, load)
    assert len(c) == 2                                                       # 오래된 것부터 버림


def test_run_dirs_sees_run_json_written_later(tmp_path):
    wd = tmp_path / "p"
    rd = create_run_dir(wd, "20261021-000001")
    dirs = RunDirs()
    assert dirs.list(wd) == []                                               # run.json 쓰기 전
    RunState(run_id=rd.name, task="t", config={}).save(rd)
    assert dirs.list(wd) == [rd]                                             # 부모 폴더가 그대로여도 보임
    rd2 = create_run_dir(wd, "20261021-000002")
    RunState(run_id=rd2.name, task="t", config={}).save(rd2)
    assert dirs.list(wd) == [rd, rd2]


def test_dashboard_reads_fresh_state_and_inbox_skips_projects(tmp_path, monkeypatch):
    wd = tmp_path / "p"
    wd.mkdir()
    Registry().add(wd)
    rd = create_run_dir(wd, "20261021-000001")
    st = RunState(run_id=rd.name, task="할일", config={})
    st.status = DONE_APPROVED
    st.save(rd)
    d = Dashboard()
    assert d.runs(str(wd))["runs"][0]["status"] == DONE_APPROVED
    st.status = RUNNING
    st.save(rd)
    assert d.runs(str(wd))["runs"][0]["status"] == RUNNING                  # 파일이 바뀌면 다시 읽음
    monkeypatch.setattr(Dashboard, "projects", lambda self: (_ for _ in ()).throw(AssertionError("projects 호출")))
    items = d.inbox()["items"]
    assert [i["run_id"] for i in items] == [rd.name]                        # 멈춘 실행(실패)으로 올라옴


def test_activity_does_not_deep_copy_state(tmp_path, monkeypatch):
    wd = tmp_path / "p"
    wd.mkdir()
    Registry().add(wd)
    rd = create_run_dir(wd, "20261021-000001")
    st = RunState(run_id=rd.name, task="t", config={})
    st.status = DONE_APPROVED
    st.save(rd)
    monkeypatch.setattr(RunState, "to_dict", lambda self: (_ for _ in ()).throw(AssertionError("to_dict")))
    assert Dashboard().runs(str(wd))["runs"][0]["activity"]["state"]


# ------------------------------------------------------------------ usage cache prune
def test_usage_cache_drops_deleted_files(tmp_path):
    usage._RECORDS.clear()
    now = dt.datetime.now(dt.timezone.utc)
    f = tmp_path / "projects" / "x" / "s.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"requestId": "a", "timestamp": now.isoformat().replace("+00:00", "Z"),
                             "message": {"usage": {"input_tokens": 1, "output_tokens": 1}}}) + "\n", encoding="utf-8")
    usage.claude_local_usage(now, home=tmp_path)
    assert str(f) in usage._RECORDS
    os.remove(f)
    usage.claude_local_usage(now, home=tmp_path)
    assert str(f) not in usage._RECORDS
