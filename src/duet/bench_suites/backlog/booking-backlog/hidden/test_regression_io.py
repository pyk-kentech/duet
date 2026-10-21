"""기존 동작이 그대로인지: 저장(형식 1·2 읽기), CLI 출력, 내보내기, 가져오기, 운영 작업, 보고서."""

import json
import os
import subprocess
import sys
from datetime import date, datetime

import pytest

from booking import Conflict, Space, StorageError
from booking import admin, storage
from booking.export import export_ics
from booking.importer import ImportError_, import_bookings
from booking.reports import utilization

NOW = datetime(2026, 10, 19, 9, 0)      # 월요일


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def dt(day, hh, mm=0, month=10):
    return datetime(2026, month, day, hh, mm)


@pytest.fixture
def clock():
    return Clock(NOW)


@pytest.fixture
def space(clock):
    s = Space(clock=clock)
    s.add_resource("room-a", "Room A", capacity=6, credits_per_hour=4)
    s.add_resource("room-b", "Room B", capacity=10, credits_per_hour=6, buffer_minutes=15)
    s.add_member("alice", "Alice", plan="pro")
    s.add_member("bob", "Bob", plan="pro")
    s.add_member("carol", "Carol")
    return s


def cli_runner(db):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")

    def cli(*args, now="2026-10-19T09:00"):
        return subprocess.run([sys.executable, "-m", "booking", "--db", str(db), "--now", now, *args],
                              capture_output=True, text=True, encoding="utf-8", env=env)
    return cli


# ---------------------------------------------------------------- 저장
V1 = {"version": 1,
      "rooms": [{"id": "room-a", "name": "Room A", "capacity": 6, "credits_per_hour": 4, "open": "09:00",
                 "close": "18:00"}],
      "members": [{"id": "alice", "name": "Alice", "plan": "basic"}],
      "bookings": [{"id": 3, "room": "room-a", "member": "alice", "start": "2026-10-20T10:00", "minutes": 90,
                    "credits": 6},
                   {"id": 5, "room": "room-a", "member": "alice", "start": "2026-10-21T10:00", "minutes": 60,
                    "credits": 4, "cancelled": True}]}


def test_v1_file_loads(clock, tmp_path):
    path = tmp_path / "v1.json"
    path.write_text(json.dumps(V1), encoding="utf-8")
    sp = storage.load(path, clock=clock)
    r = sp.resource("room-a")
    assert (r.kind, r.capacity, r.buffer_minutes) == ("room", 6, 0)
    assert sp.free_slots("room-a", date(2026, 10, 24), 60) == []                 # 토요일 닫힘
    b, c = sp.booking(3), sp.booking(5)
    assert (b.end, b.charged, b.created_at, b.active) == (dt(20, 11, 30), 6, datetime(2000, 1, 1), True)
    assert (c.status, c.fee) == ("cancelled", 0)
    assert sp.balance("alice", "2026-10") == 34
    with pytest.raises(Conflict):
        sp.book("room-a", "alice", dt(20, 11), dt(20, 12))
    assert sp.book("room-a", "alice", dt(20, 12), dt(20, 13)).id == 6


def test_reload_keeps_conflicts(space, clock, tmp_path):
    space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    space.book("room-b", "bob", dt(20, 10), dt(20, 11))
    path = tmp_path / "b.json"
    storage.save(space, path)
    sp = storage.load(path, clock=clock)
    with pytest.raises(Conflict):
        sp.book("room-a", "carol", dt(20, 10, 30), dt(20, 11, 30))
    with pytest.raises(Conflict):
        sp.book("room-b", "carol", dt(20, 11), dt(20, 12))                       # 버퍼
    assert sp.book("room-a", "carol", dt(20, 11), dt(20, 12)).id == 3
    assert sp.balance("alice", "2026-10") == 116


def test_broken_files(tmp_path):
    path = tmp_path / "x.json"
    for bad in ("{nope", "[]", '{"version": 2, "bookings": [{"id": 1}]}',
                '{"version": 2, "resources": [], "members": [], "bookings": [{"id": 1, "resource": "x", "member": "y",'
                ' "start": "2026-10-20T10:00:00", "end": "2026-10-20T11:00:00"}]}'):
        path.write_text(bad, encoding="utf-8")
        with pytest.raises(StorageError):
            storage.load(path)


# ---------------------------------------------------------------- CLI
def test_cli_error_leaves_file(tmp_path):
    db = tmp_path / "b.json"
    cli = cli_runner(db)
    assert cli("resource-add", "room-a", "Room A", "--capacity", "6").returncode == 0
    assert cli("member-add", "alice", "Alice").returncode == 0
    assert cli("book", "room-a", "alice", "2026-10-20T10:00", "2026-10-20T11:00").returncode == 0
    before = db.read_bytes()
    for args in (("book", "room-a", "alice", "2026-10-20T10:30", "2026-10-20T11:30"), ("cancel", "9"),
                 ("book", "room-a", "nobody", "2026-10-20T12:00", "2026-10-20T13:00"),
                 ("resource-add", "Bad", "x")):
        r = cli(*args)
        assert r.returncode == 1 and r.stderr.startswith("오류:"), args
    assert db.read_bytes() == before


def test_cli_outputs(tmp_path):
    cli = cli_runner(tmp_path / "b.json")
    for args in (("resource-add", "room-a", "Room A", "--capacity", "6"),
                 ("resource-add", "desk-1", "Desk 1", "--kind", "desk", "--cph", "1", "--buffer", "15",
                  "--hours", "sat 10:00-14:00; mon-fri 07:00-22:00"),
                 ("member-add", "bob", "Bob", "--plan", "pro"), ("member-add", "alice", "Alice"),
                 ("book", "room-a", "bob", "2026-10-21T10:00", "2026-10-21T11:00"),
                 ("book", "desk-1", "alice", "2026-10-20T09:00", "2026-10-20T12:00", "--note", "집중"),
                 ("cancel", "1")):
        r = cli(*args)
        assert r.returncode == 0, (args, r.stderr)
    assert cli("resources").stdout.splitlines() == [
        "desk-1\tdesk\t1\t1\t15\tmon-fri 07:00-22:00; sat 10:00-14:00", "room-a\troom\t6\t4\t0\tmon-fri 08:00-20:00"]
    assert cli("list").stdout.splitlines() == ["2\tdesk-1\talice\t2026-10-20T09:00\t2026-10-20T12:00\tactive\t3"]
    assert cli("list", "--all", "--resource", "room-a").stdout.splitlines() == [
        "1\troom-a\tbob\t2026-10-21T10:00\t2026-10-21T11:00\tcancelled\t4"]
    assert cli("balance", "alice", now="2026-11-02T09:00").stdout.strip() == "alice\t2026-11\t40\t0\t40"
    assert cli("usage", "2026-10").stdout.splitlines() == ["alice\tbasic\t40\t3\t37", "bob\tpro\t120\t0\t120"]
    assert cli("report", "2026-10-20", "2026-10-21").stdout.splitlines() == ["desk-1\t900\t180\t20.0",
                                                                             "room-a\t720\t0\t0.0"]
    assert cli("agenda", "2026-10-20").stdout.splitlines() == ["desk-1\t2026-10-20T09:00\t2026-10-20T12:00\talice\t집중"]
    assert cli("notifications", "--member", "bob").stdout.splitlines() == [
        "2026-10-19T09:00\tbob\tcancelled\t예약 1 취소 · 수수료 0 · 환불 4"]


def test_export_ics_exact(space):
    space.add_resource("odd", "Room, A; x", capacity=2, credits_per_hour=2)
    s = space.book_series("odd", "bob", dt(20, 9), dt(20, 10), count=1, note="줄1\n줄2")
    space.book("room-a", "alice", dt(20, 8), dt(20, 9))
    gone = space.book("room-a", "alice", dt(21, 8), dt(21, 9))
    space.cancel(gone.id)
    assert export_ics(space) == "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//booking//coworking//KO",
        "BEGIN:VEVENT", "UID:booking-2@booking.local", "DTSTART:20261020T080000", "DTEND:20261020T090000",
        "SUMMARY:Room A (alice)", "END:VEVENT",
        "BEGIN:VEVENT", f"UID:booking-{s.booking_ids[0]}@booking.local", "DTSTART:20261020T090000",
        "DTEND:20261020T100000", "SUMMARY:Room\\, A\\; x (bob)", "DESCRIPTION:줄1\\n줄2", f"CATEGORIES:series-{s.id}",
        "END:VEVENT", "END:VCALENDAR"]) + "\r\n"


# ---------------------------------------------------------------- 가져오기
CSV_BAD = "resource,member,start,end\nroom-a,alice,2026-10-20T09:00,2026-10-20T10:00\n" \
          "room-b,bob,2026-10-20T13:00,2026-10-20T14:00\nroom-b,bob,2026-10-20T16:00,2026-10-20T17:00\n"


@pytest.fixture
def failed_import(space):
    space.book("room-b", "carol", dt(20, 15), dt(20, 16))
    with pytest.raises(ImportError_) as err:
        import_bookings(space, CSV_BAD)
    assert err.value.line == 4
    return space


def test_failed_import_restores_bookings_and_credits(failed_import):
    space = failed_import
    assert [b.id for b in space.bookings()] == [1]
    assert space.balance("alice", "2026-10") == 120 and space.balance("bob", "2026-10") == 120
    assert len(space.ledger()) == 1


def test_failed_import_frees_the_slots(failed_import):
    space = failed_import
    assert space.book("room-a", "bob", dt(20, 9), dt(20, 10)).id == 2                # 되돌린 자리는 비어 있다
    assert space.book("room-b", "alice", dt(20, 13), dt(20, 14)).id == 3


# ---------------------------------------------------------------- 운영 작업
def test_purge_cancelled(space, clock):
    s = space.book_series("room-a", "alice", dt(22, 10), dt(22, 11), count=2)
    free = space.book("room-a", "bob", dt(22, 12), dt(22, 13))
    late = space.book("room-a", "bob", dt(19, 14), dt(19, 15))
    clock.t = dt(19, 13)
    space.cancel(free.id)                                                        # 71시간 전: 수수료 0
    space.cancel(late.id)                                                        # 1시간 전: 수수료 4
    space.skip_occurrence(s.id, date(2026, 10, 22))
    before = space.balance("bob", "2026-10"), space.balance("alice", "2026-10")
    assert admin.purge_cancelled(space, dt(1, 0, month=11)) == 2
    ids = {b.id for b in space.bookings(include_cancelled=True)}
    assert late.id in ids and free.id not in ids and s.booking_ids == [s.booking_ids[-1]]
    assert (space.balance("bob", "2026-10"), space.balance("alice", "2026-10")) == before


def test_check_integrity_ignores_buffer(space):
    space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    space.book("room-a", "bob", dt(20, 11), dt(20, 12))
    space.update_resource("room-a", buffer_minutes=30)                           # 기존 예약은 다시 보지 않는다
    assert admin.check_integrity(space) == []


# ---------------------------------------------------------------- 보고서
def test_utilization_window_and_rounding(space):
    space.book("room-a", "alice", dt(20, 9), dt(20, 10))
    space.book("room-a", "bob", dt(20, 11), dt(20, 11, 30))
    [row] = utilization(space, dt(20, 9, 30), dt(20, 12), resource_id="room-a")
    assert (row.open_minutes, row.booked_minutes, row.percent) == (150, 60, 40.0)
    [row] = utilization(space, dt(20, 8), dt(20, 11), resource_id="room-a")
    assert (row.open_minutes, row.booked_minutes, row.percent) == (180, 60, 33.3)


def test_utilization_counts_bookings_outside_current_hours(space):
    space.book("room-a", "alice", dt(20, 18), dt(20, 20))
    space.update_resource("room-a", hours="mon-fri 09:00-17:00")
    [row] = utilization(space, dt(20, 0), dt(21, 0), resource_id="room-a")
    assert (row.open_minutes, row.booked_minutes, row.percent) == (480, 120, 25.0)
