"""#6 저장 형식 3: 대기열·팀 저장, 형식 1·2 읽기, 모르는 버전 거부."""

import json
import os
import subprocess
import sys
from datetime import datetime
from decimal import Decimal

import pytest

from booking import Space, StorageError
from booking import storage

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
    s.add_member("alice", "Alice", plan="pro")
    s.add_member("bob", "Bob", plan="pro")
    s.add_member("carol", "Carol")
    return s


# ---------------------------------------------------------------- 쓰기
@pytest.fixture
def saved(space, tmp_path):
    space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    space.join_waitlist("room-a", "bob", dt(20, 10), dt(20, 11))
    space.add_team("core", "Core", 30, "2.50")
    space.join_team("carol", "core")
    space.book("room-a", "carol", dt(21, 10), dt(21, 11))
    path = tmp_path / "b.json"
    storage.save(space, path)
    return json.loads(path.read_text(encoding="utf-8"))


def test_saved_version_and_waitlist(saved):
    assert saved["version"] == 3
    [w] = saved["waitlist"]
    assert (w["id"], w["resource"], w["member"], w["attendees"]) == (1, "room-a", "bob", 1)
    assert datetime.fromisoformat(w["start"]) == dt(20, 10) and datetime.fromisoformat(w["created_at"]) == NOW


def test_saved_next_waitlist_id(saved):
    assert saved["next_ids"]["waitlist"] == 2


def test_saved_teams(saved):
    assert saved["teams"] == [{"id": "core", "name": "Core", "monthly_credits": 30, "overage_price": "2.50",
                               "members": ["carol"]}]


def test_saved_accounts(saved):
    assert [b["account"] for b in saved["bookings"]] == ["member:alice", "team:core"]
    assert [e["account"] for e in saved["ledger"]] == ["member:alice", "team:core"]


# ---------------------------------------------------------------- 대기열 왕복
def test_waitlist_roundtrip_keeps_order(space, clock, tmp_path):
    space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    clock.t = dt(19, 9, 5)
    space.join_waitlist("room-a", "carol", dt(20, 10), dt(20, 11))
    clock.t = dt(19, 9, 10)
    space.join_waitlist("room-a", "bob", dt(20, 10, 30), dt(20, 11, 30), attendees=3)
    path = tmp_path / "b.json"
    storage.save(space, path)
    again = storage.load(path, clock=clock)
    got = [(e.id, e.resource_id, e.member_id, e.start, e.end, e.attendees, e.created_at) for e in again.waitlist()]
    assert got == [(1, "room-a", "carol", dt(20, 10), dt(20, 11), 1, dt(19, 9, 5)),
                   (2, "room-a", "bob", dt(20, 10, 30), dt(20, 11, 30), 3, dt(19, 9, 10))]


def test_waitlist_ids_not_reused_after_reload(space, clock, tmp_path):
    space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    space.join_waitlist("room-a", "bob", dt(20, 10), dt(20, 11))
    e2 = space.join_waitlist("room-a", "carol", dt(20, 10), dt(20, 11))
    space.leave_waitlist(e2.id)
    path = tmp_path / "b.json"
    storage.save(space, path)
    again = storage.load(path, clock=clock)
    assert again.join_waitlist("room-a", "carol", dt(20, 10), dt(20, 11)).id == 3


def test_promotion_after_reload(space, clock, tmp_path):
    b = space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    space.join_waitlist("room-a", "bob", dt(20, 10), dt(20, 11))
    path = tmp_path / "b.json"
    storage.save(space, path)
    again = storage.load(path, clock=clock)
    again.cancel(b.id)
    assert [x.member_id for x in again.bookings()] == ["bob"] and again.waitlist() == []


# ---------------------------------------------------------------- 팀 왕복
@pytest.fixture
def team_reloaded(space, clock, tmp_path):
    space.add_team("core", "Core", 30, "2.50")
    space.add_team("alpha", "Alpha", 0)
    space.join_team("carol", "core")
    space.join_team("alice", "core")
    b = space.book("room-a", "carol", dt(20, 10), dt(20, 12))
    path = tmp_path / "b.json"
    storage.save(space, path)
    return storage.load(path, clock=clock), b.id


def test_teams_roundtrip(team_reloaded):
    again, _bid = team_reloaded
    assert [(t.id, t.name, t.monthly_credits, t.overage_price, t.members) for t in again.teams()] == [
        ("alpha", "Alpha", 0, None, []), ("core", "Core", 30, Decimal("2.50"), ["alice", "carol"])]
    assert again.member("carol").team == "core" and again.member("bob").team is None


def test_accounts_roundtrip(team_reloaded):
    again, bid = team_reloaded
    assert again.booking(bid).account == "team:core" and again.team_balance("core", "2026-10") == 22
    assert [e.account for e in again.ledger("carol")] == ["team:core"]
    assert again.book("room-a", "alice", dt(22, 10), dt(22, 11)).account == "team:core"


def test_refund_after_reload_goes_to_team(space, clock, tmp_path):
    space.add_team("core", "Core", 30)
    space.join_team("alice", "core")
    b = space.book("room-a", "alice", dt(22, 10), dt(22, 12))
    space.leave_team("alice")
    path = tmp_path / "b.json"
    storage.save(space, path)
    again = storage.load(path, clock=clock)
    again.cancel(b.id)
    assert again.team_balance("core", "2026-10") == 30 and again.balance("alice", "2026-10") == 120


# ---------------------------------------------------------------- 예전 형식
V2 = {
    "version": 2,
    "next_ids": {"booking": 4, "series": 2},
    "resources": [{"id": "room-a", "name": "Room A", "kind": "room", "capacity": 6, "credits_per_hour": 4,
                   "buffer_minutes": 0, "hours": "mon-fri 08:00-20:00"}],
    "members": [{"id": "alice", "name": "Alice", "plan": "basic"}, {"id": "bob", "name": "Bob", "plan": "pro"}],
    "bookings": [
        {"id": 1, "resource": "room-a", "member": "alice", "start": "2026-10-20T10:00:00", "end": "2026-10-20T11:00:00",
         "attendees": 2, "note": "hi", "status": "active", "series": None, "charged": 4, "fee": None,
         "created_at": "2026-10-10T09:00:00", "cancelled_at": None},
        {"id": 2, "resource": "room-a", "member": "bob", "start": "2026-10-21T10:00:00", "end": "2026-10-21T11:00:00",
         "attendees": 1, "note": "", "status": "active", "series": 1, "charged": 4, "fee": None,
         "created_at": "2026-10-10T09:00:00", "cancelled_at": None},
        {"id": 3, "resource": "room-a", "member": "alice", "start": "2026-10-16T10:00:00",
         "end": "2026-10-16T11:00:00", "attendees": 1, "note": "", "status": "cancelled", "series": None,
         "charged": 4, "fee": 4, "created_at": "2026-10-10T09:00:00", "cancelled_at": "2026-10-16T09:30:00"}],
    "series": [{"id": 1, "resource": "room-a", "member": "bob", "start": "2026-10-21T10:00:00",
                "end": "2026-10-21T11:00:00", "freq": "weekly", "count": 1, "until": None, "exceptions": [],
                "bookings": [2]}],
    "ledger": [
        {"ts": "2026-10-10T09:00:00", "member": "alice", "month": "2026-10", "kind": "charge", "credits": 4,
         "booking": 1, "note": "booking"},
        {"ts": "2026-10-10T09:00:00", "member": "bob", "month": "2026-10", "kind": "charge", "credits": 4,
         "booking": 2, "note": "booking"},
        {"ts": "2026-10-10T09:00:00", "member": "alice", "month": "2026-10", "kind": "charge", "credits": 4,
         "booking": 3, "note": "booking"}],
    "notifications": [{"ts": "2026-10-16T09:30:00", "member": "alice", "kind": "cancelled",
                       "text": "예약 3 취소 · 수수료 4 · 환불 0"}],
}


def _summary(sp):
    return ([(b.id, b.resource_id, b.member_id, b.start, b.end, b.attendees, b.note, b.status, b.series_id, b.charged,
              b.fee, b.created_at, b.cancelled_at, b.account) for b in sp.bookings(include_cancelled=True)],
            [(s.id, s.booking_ids, s.freq) for s in sp.all_series()],
            [(e.member_id, e.month, e.kind, e.credits, e.booking_id, e.account) for e in sp.ledger()],
            [(n.member_id, n.kind, n.text) for n in sp.notifications()],
            sp.balance("alice", "2026-10"), sp.balance("bob", "2026-10"))


def test_v2_file_upgrade_keeps_everything(clock, tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps(V2, ensure_ascii=False), encoding="utf-8")
    sp = storage.load(path, clock=clock)
    assert sp.waitlist() == [] and sp.teams() == []
    assert [b.account for b in sp.bookings(include_cancelled=True)] == ["member:alice", "member:alice", "member:bob"]
    before = _summary(sp)
    assert before[-2:] == (32, 116)
    storage.save(sp, path)
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 3
    again = storage.load(path, clock=clock)
    assert _summary(again) == before
    assert again.book("room-a", "alice", dt(22, 10), dt(22, 11)).id == 4


def test_v1_file_is_upgraded_without_loss(clock, tmp_path):
    v1 = {"version": 1,
          "rooms": [{"id": "room-a", "name": "Room A", "capacity": 6, "credits_per_hour": 4, "open": "09:00",
                     "close": "18:00"}],
          "members": [{"id": "alice", "name": "Alice", "plan": "basic"}],
          "bookings": [{"id": 7, "room": "room-a", "member": "alice", "start": "2026-10-20T10:00", "minutes": 90,
                        "credits": 6}]}
    path = tmp_path / "v1.json"
    path.write_text(json.dumps(v1), encoding="utf-8")
    storage.save(storage.load(path, clock=clock), path)
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 3
    sp = storage.load(path, clock=clock)
    [b] = sp.bookings()
    assert (b.id, b.end, b.charged, b.created_at, b.account) == (7, dt(20, 11, 30), 6, datetime(2000, 1, 1),
                                                                   "member:alice")
    assert sp.balance("alice", "2026-10") == 34


def test_unknown_versions_rejected(tmp_path):
    path = tmp_path / "x.json"
    for version in (4, "3", None):
        data = dict(V2)
        if version is None:
            data.pop("version")
        else:
            data["version"] = version
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(StorageError):
            storage.load(path)


# ---------------------------------------------------------------- 형식 3 검사
@pytest.fixture
def good_v3(space, tmp_path):
    space.add_team("core", "Core", 30)
    space.join_team("alice", "core")
    space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    space.join_waitlist("room-a", "bob", dt(20, 10), dt(20, 11))
    path = tmp_path / "b.json"
    storage.save(space, path)
    return path, json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("mutate", [
    lambda d: d["teams"][0]["members"].append("ghost"),
    lambda d: d["bookings"][0].__setitem__("account", "team:nope"),
    lambda d: d["waitlist"][0].__setitem__("resource", "room-z"),
], ids=["team-member", "booking-account", "waitlist-resource"])
def test_v3_bad_references_rejected(good_v3, mutate):
    path, good = good_v3
    bad = json.loads(json.dumps(good))
    mutate(bad)
    path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(StorageError):
        storage.load(path)


# ---------------------------------------------------------------- CLI
def test_cli_waitlist_persists(tmp_path):
    db = tmp_path / "b.json"
    env = dict(os.environ, PYTHONIOENCODING="utf-8")

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "booking", "--db", str(db), "--now", "2026-10-19T09:00", *args],
                              capture_output=True, text=True, encoding="utf-8", env=env)

    for args in (("resource-add", "room-a", "Room A", "--capacity", "6"), ("member-add", "alice", "Alice"),
                 ("member-add", "bob", "Bob")):
        assert cli(*args).returncode == 0
    assert cli("book", "room-a", "alice", "2026-10-22T10:00", "2026-10-22T11:00").returncode == 0
    assert cli("wait", "room-a", "bob", "2026-10-22T10:00", "2026-10-22T11:00").stdout.strip() == "1"
    assert cli("waitlist").stdout.splitlines() == ["1\troom-a\tbob\t2026-10-22T10:00\t2026-10-22T11:00"]
    assert cli("cancel", "1").returncode == 0
    assert cli("waitlist").stdout == ""
    assert cli("list").stdout.splitlines() == ["2\troom-a\tbob\t2026-10-22T10:00\t2026-10-22T11:00\tactive\t4"]
