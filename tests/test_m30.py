"""M30: tenure 엔진 기반 (DESIGN.md 36장). 실제 claude/codex 는 부르지 않는다."""

from __future__ import annotations

import json
from pathlib import Path

from tenure import legacy
from tenure.cli import main
from tenure.config import load_config
from tenure.lock import RunLock
from tenure.registry import tenure_home
from tenure.state import LEGACY_DIR, TENURE_DIR, list_run_dirs, project_dir


# ====================================================================== 36.11 옛 이름 duet 호환
def test_env_aliases_copy_old_names_without_overriding():
    env = {"DUET_HOME": "/old", "DUET_MOCK_DELAY": "1", "TENURE_MOCK_DELAY": "2", "OTHER": "x"}
    legacy.apply_env_aliases(env)
    assert env["TENURE_HOME"] == "/old" and env["TENURE_MOCK_DELAY"] == "2" and "TENURE_OTHER" not in env


def test_project_dir_migrates_legacy_folder(tmp_path: Path):
    old = tmp_path / LEGACY_DIR / "runs" / "20261001-000000"
    old.mkdir(parents=True)
    (old / "run.json").write_text("{}", encoding="utf-8")
    assert project_dir(tmp_path) == tmp_path / TENURE_DIR
    assert (tmp_path / TENURE_DIR / "runs" / "20261001-000000" / "run.json").is_file()
    assert not (tmp_path / LEGACY_DIR).exists()
    assert project_dir(tmp_path) == tmp_path / TENURE_DIR          # 두 번째는 그대로


def test_project_dir_keeps_new_folder_when_both_exist(tmp_path: Path):
    (tmp_path / LEGACY_DIR).mkdir()
    (tmp_path / TENURE_DIR).mkdir()
    assert project_dir(tmp_path) == tmp_path / TENURE_DIR and (tmp_path / LEGACY_DIR).is_dir()


def test_home_migrates_legacy_folder(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TENURE_HOME", raising=False)
    monkeypatch.delenv("DUET_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / ".duet").mkdir()
    (tmp_path / ".duet" / "projects.json").write_text("[]", encoding="utf-8")
    assert tenure_home() == tmp_path / ".tenure"
    assert (tmp_path / ".tenure" / "projects.json").is_file() and not (tmp_path / ".duet").exists()


def test_legacy_config_file_is_read(tmp_path: Path):
    (tmp_path / "duet.toml").write_text("max_review = 4\n", encoding="utf-8")
    assert load_config(tmp_path).max_review == 4
    (tmp_path / "tenure.toml").write_text("max_review = 2\n", encoding="utf-8")
    assert load_config(tmp_path).max_review == 2                    # 새 이름이 이긴다


def test_old_runs_and_lock_paths_follow_migration(tmp_path: Path):
    run = tmp_path / LEGACY_DIR / "runs" / "20261001-000000"
    run.mkdir(parents=True)
    (run / "run.json").write_text("{}", encoding="utf-8")
    assert [p.name for p in list_run_dirs(tmp_path)] == ["20261001-000000"]
    with RunLock(tmp_path, command="tenure run"):
        assert (tmp_path / TENURE_DIR / "lock.json").is_file()


def test_mock_run_writes_new_folder_and_cli_name(tmp_path: Path, capsys):
    assert main(["run", "할일 CLI", "--workdir", str(tmp_path), "--mock", "--debate-rounds", "0"]) == 0
    assert (tmp_path / TENURE_DIR / "runs").is_dir() and not (tmp_path / LEGACY_DIR).exists()
    st = json.loads(next((tmp_path / TENURE_DIR / "runs").iterdir()).joinpath("run.json").read_text(encoding="utf-8"))
    assert st["status"].startswith("done")


# ====================================================================== 36.3 상태 어휘·결과 계약·이벤트
import datetime as dt
import threading
import urllib.request

import pytest

from tenure import events
from tenure.agents.base import AgentResult
from tenure.outcome import run_activity, step_outcome
from tenure.state import RunState
from tenure.ui.dashboard import Dashboard
from tenure.ui.server import make_server


def _res(**kw) -> AgentResult:
    base = dict(text="", raw_stdout="", raw_stderr="", exit_code=0, duration_sec=1.0)
    base.update(kw)
    return AgentResult(**base)


@pytest.mark.parametrize("kw, want", [
    ({}, ("done", "")),
    ({"rate_limited": True, "exit_code": 1}, ("blocked", "구독 한도")),
    ({"timed_out": True, "exit_code": -1}, ("failed", "시간 초과")),
    ({"exit_code": 1, "raw_stderr": "Error: Not logged in. Please run /login"}, ("blocked", "로그인 필요")),
    ({"exit_code": 1, "raw_stderr": "Do you trust this folder?"}, ("blocked", "폴더 신뢰 필요")),
])
def test_step_outcome(kw, want):
    out, why = step_outcome(_res(**kw))
    assert out == want[0] and (why == want[1] or (want[0] == "failed" and why))


def test_step_outcome_unconfirmed_without_structured():
    assert step_outcome(_res(text="본문"), expect_structured=True)[0] == "unconfirmed"


def test_run_activity_states():
    now = dt.datetime(2026, 10, 21, 12, 0, 0)
    run = {"status": "running"}
    assert run_activity(run, live=True, last_ts="2026-10-21T11:59:00", now=now)["state"] == "working"
    assert run_activity(run, live=True, last_ts="2026-10-21T11:30:00", now=now)["state"] == "unverifiable"
    assert run_activity(run, live=False, now=now)["state"] == "failed"
    assert run_activity({**run, "limit_wait": {"until": "2026-10-21T13:00:00"}}, live=True, now=now)["state"] == "blocked"
    done = {"status": "done_unapproved"}
    unseen = run_activity(done, live=False, last_ts="2026-10-21T11:00:00", now=now)
    assert unseen["state"] == "done-unseen" and "미승인" in unseen["reason"] and unseen["rank"] == 3
    assert run_activity({**done, "seen_at": "2026-10-21T11:30:00"}, live=False, last_ts="2026-10-21T11:00:00",
                        now=now)["state"] == "idle"
    assert run_activity({"status": "stopped_rate_limit"}, live=False, now=now)["rank"] == 4


def test_event_log_seq_continues_across_instances(tmp_path: Path):
    a = events.EventLog(tmp_path)
    a.emit(events.LOG, text="1")
    a.emit(events.LOG, text="2")
    b = events.EventLog(tmp_path)                       # 다시 열어도 seq 가 이어진다
    assert b.emit(events.LOG, text="3")["seq"] == 3
    assert [e["text"] for e in events.read_events(tmp_path, since=1)] == ["2", "3"]


def test_mock_run_writes_events_and_outcomes(tmp_path: Path):
    assert main(["run", "할일 CLI", "--workdir", str(tmp_path), "--mock", "--debate-rounds", "0"]) == 0
    [rd] = list_run_dirs(tmp_path)
    evs = events.read_events(rd)
    seqs = [e["seq"] for e in evs]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    kinds = {e["kind"] for e in evs}
    assert {"state", "step_start", "step_end", "log"} <= kinds
    ends = [e for e in evs if e["kind"] == "step_end"]
    assert ends and all(e["outcome"] in ("done", "unconfirmed") for e in ends)
    assert evs[-1]["kind"] in ("state", "log")
    st = RunState.load(rd)
    assert st.calls and all(c.outcome for c in st.calls)


def test_dashboard_events_seen_and_inbox(tmp_path: Path):
    wd = tmp_path / "proj"
    assert main(["run", "할일 CLI", "--workdir", str(wd), "--mock", "--debate-rounds", "0"]) == 0
    dash = Dashboard()
    dash.add_project(str(wd))
    [rd] = list_run_dirs(wd)
    page = dash.events(str(wd), rd.name, since=0)
    assert page["events"] and page["last_seq"] == page["events"][-1]["seq"]
    assert dash.events(str(wd), rd.name, since=page["last_seq"])["events"] == []
    box = dash.inbox()
    assert [i["run_id"] for i in box["items"]] == [rd.name] and box["items"][0]["activity"]["state"] == "done-unseen"
    assert dash.mark_seen(str(wd), rd.name)["ok"]
    assert dash.inbox()["items"] == []
    assert dash.run(str(wd), rd.name)["activity"]["state"] == "idle"


def test_sse_stream_sends_events_then_end(tmp_path: Path):
    wd = tmp_path / "proj"
    assert main(["run", "할일 CLI", "--workdir", str(wd), "--mock", "--debate-rounds", "0"]) == 0
    dash = Dashboard()
    dash.add_project(str(wd))
    [rd] = list_run_dirs(wd)
    srv = make_server("127.0.0.1", 0, dashboard=dash, token="t-m30")
    th = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    th.start()
    try:
        from urllib.parse import quote
        url = f"http://127.0.0.1:{srv.server_address[1]}/api/stream?project={quote(str(wd))}&run={rd.name}&since=0"
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"X-Tenure-Token": "t-m30"}), timeout=20)
        assert r.headers["Content-Type"].startswith("text/event-stream")
        body = r.read().decode("utf-8")                # 끝난 실행이라 이벤트를 다 보내고 end 로 닫는다
        assert "event: step_end" in body and body.rstrip().endswith("data: {}") and "event: end" in body
        ids = [int(line[4:]) for line in body.splitlines() if line.startswith("id: ")]
        assert ids == sorted(ids) and ids[0] == 1
    finally:
        srv.shutdown()
        srv.server_close()
