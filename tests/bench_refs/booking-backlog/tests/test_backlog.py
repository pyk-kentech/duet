"""백로그 티켓(#1~#8) 테스트."""

import json
from datetime import date, datetime

import pytest

from booking import Conflict, InsufficientCredits, Space, StorageError
from booking import storage
from booking.reports import utilization


def dt(day, hh, mm=0, month=10):
    return datetime(2026, month, day, hh, mm)


def test_buffer_applies_to_series_move_waitlist_and_free_slots(space):
    space.book("room-b", "alice", dt(20, 10), dt(20, 11))
    with pytest.raises(Conflict):
        space.book_series("room-b", "bob", dt(20, 11), dt(20, 12), count=2)
    other = space.book("room-b", "bob", dt(20, 14), dt(20, 15))
    with pytest.raises(Conflict):
        space.move(other.id, dt(20, 11), dt(20, 12))
    assert space.join_waitlist("room-b", "bob", dt(20, 11), dt(20, 12)).id == 1
    slots = space.free_slots("room-b", date(2026, 10, 20), 60)
    assert dt(20, 8, 45) in slots and dt(20, 9) not in slots and dt(20, 11) not in slots


def test_overnight_hours(space):
    space.add_resource("lab", "Lab", capacity=4, credits_per_hour=4, hours="fri 22:00-02:00")
    space.book("lab", "alice", dt(23, 23), dt(24, 1))
    space.book("lab", "bob", dt(24, 1), dt(24, 2))
    [sat] = utilization(space, dt(24, 0), dt(25, 0), resource_id="lab")
    assert (sat.open_minutes, sat.booked_minutes) == (120, 120)
    assert space.free_slots("lab", date(2026, 10, 23), 60) == [dt(23, 22)]


def test_new_fee_table_grace_and_waiver(space, clock):
    space.add_resource("big", "Big", capacity=8, credits_per_hour=10)
    a = space.book("big", "bob", dt(21, 10), dt(21, 11))
    b = space.book("big", "bob", dt(19, 14), dt(19, 15))
    space.join_waitlist("big", "alice", dt(19, 14), dt(19, 15))
    clock.t = dt(19, 9, 10)
    c = space.book("big", "bob", dt(19, 16), dt(19, 17))
    assert space.cancel(c.id).fee == 0                            # 유예
    clock.t = dt(19, 10, 15)
    assert space.cancel(a.id).fee == 3                            # 47시간 45분: 25%
    clock.t = dt(19, 13)
    assert space.cancel(b.id).fee == 0                            # 대기자가 이어받음


def test_team_credits_and_refund_account(space, clock):
    space.add_team("core", "Core", 10)
    space.join_team("alice", "core")
    b = space.book("room-a", "alice", dt(22, 10), dt(22, 12))
    assert (b.account, space.team_balance("core", "2026-10")) == ("team:core", 2)
    with pytest.raises(InsufficientCredits):
        space.book("room-a", "alice", dt(22, 13), dt(22, 14))
    space.leave_team("alice")
    clock.t = dt(19, 10)
    space.cancel(b.id)
    assert space.team_balance("core", "2026-10") == 10


def test_storage_v3_roundtrip_and_versions(space, clock, tmp_path):
    space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    space.join_waitlist("room-a", "bob", dt(20, 10), dt(20, 11))
    space.add_team("core", "Core", 10, "2.50")
    path = tmp_path / "b.json"
    storage.save(space, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 3 and data["next_ids"]["waitlist"] == 2
    again = storage.load(path, clock=clock)
    assert [e.member_id for e in again.waitlist()] == ["bob"] and str(again.team("core").overage_price) == "2.50"
    data["version"] = 4
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(StorageError):
        storage.load(path)


def test_move_recharges(space):
    b = space.book("room-a", "alice", dt(30, 10), dt(30, 11))
    space.move(b.id, dt(30, 10), dt(30, 12))
    assert space.balance("alice", "2026-10") == 32
    space.move(b.id, dt(2, 10, month=11), dt(2, 11, month=11))
    assert (space.balance("alice", "2026-10"), space.balance("alice", "2026-11")) == (40, 36)
