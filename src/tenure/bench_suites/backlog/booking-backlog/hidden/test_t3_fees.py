"""#3 새 취소 수수료 표와 유예 시간."""

import os
import subprocess
import sys
from datetime import date, datetime

import pytest

from booking import Space

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
    s.add_resource("big", "Big", capacity=8, credits_per_hour=10)
    s.add_member("alice", "Alice", plan="pro")
    s.add_member("bob", "Bob", plan="pro")
    return s


# ---------------------------------------------------------------- 표
def test_quarter_fee_between_24_and_48_hours(space, clock):
    b = space.book("big", "alice", dt(21, 10), dt(21, 11))
    clock.t = dt(19, 10, 15)                                   # 47시간 45분 전
    c = space.cancel(b.id)
    assert (c.fee, c.refund, b.fee) == (3, 7, 3)               # 10 의 25% = 2.5 → 3
    assert space.balance("alice", "2026-10") == 117


def test_exactly_48_hours_is_free(space, clock):
    a = space.book("big", "alice", dt(21, 10), dt(21, 11))
    b = space.book("big", "alice", dt(21, 11), dt(21, 12))
    clock.t = dt(19, 11)
    assert (space.cancel(a.id).fee, space.cancel(b.id).fee) == (3, 0)     # 47시간, 48시간


def test_exactly_24_hours_is_quarter(space, clock):
    a = space.book("room-a", "alice", dt(20, 10), dt(20, 10, 30))      # 2 크레딧
    b = space.book("big", "alice", dt(20, 12), dt(20, 13))
    clock.t = dt(19, 10)
    assert space.cancel(a.id).fee == 1                         # 0.5 → 1
    clock.t = dt(19, 12, 1)
    assert space.cancel(b.id).fee == 5                         # 23시간 59분: 50%


def test_quarter_fee_rounds_up(space, clock):
    b = space.book("room-a", "alice", dt(22, 10), dt(22, 12, 15))       # 9 크레딧
    clock.t = dt(20, 12)
    c = space.cancel(b.id)
    assert (c.fee, c.refund) == (3, 6)                         # 2.25 → 3


# ---------------------------------------------------------------- 유예
def test_grace_exactly_15_minutes(space, clock):
    a = space.book("big", "alice", dt(19, 10), dt(19, 11))
    clock.t = dt(19, 9, 15)
    c = space.cancel(a.id)
    assert (c.fee, c.refund) == (0, 10)


def test_grace_over_after_16_minutes(space, clock):
    b = space.book("big", "alice", dt(19, 11), dt(19, 12))
    clock.t = dt(19, 9, 16)
    assert space.cancel(b.id).fee == 10


def test_grace_for_series_occurrences(space, clock):
    s = space.book_series("big", "alice", dt(19, 11), dt(19, 12), count=3)
    clock.t = dt(19, 9, 10)
    assert [(r.fee, r.refund) for r in space.cancel_series(s.id)] == [(0, 10), (0, 10), (0, 10)]


def test_promoted_booking_grace_starts_at_promotion(space, clock):
    a = space.book("big", "alice", dt(20, 10), dt(20, 11))
    space.join_waitlist("big", "bob", dt(20, 10), dt(20, 11))
    clock.t = dt(20, 9)
    space.cancel(a.id)
    [nb] = space.bookings(member_id="bob")
    clock.t = dt(20, 9, 10)
    assert nb.created_at == dt(20, 9) and space.cancel(nb.id).fee == 0


def test_move_does_not_restart_grace(space, clock):
    b = space.book("room-a", "alice", dt(19, 14), dt(19, 15))
    clock.t = dt(19, 9, 30)
    space.move(b.id, dt(19, 15), dt(19, 16))
    clock.t = dt(19, 9, 35)
    assert b.created_at == NOW and space.cancel(b.id).fee == 2           # 5시간 25분 전: 50%


# ---------------------------------------------------------------- 다른 취소 경로
def test_skip_occurrence_uses_new_table(space, clock):
    s = space.book_series("big", "alice", dt(21, 10), dt(21, 11), count=2)
    clock.t = dt(19, 12)
    c = space.skip_occurrence(s.id, date(2026, 10, 21))         # 46시간 전
    assert (c.fee, c.refund) == (3, 7)


def test_cancel_series_new_table_per_occurrence(space, clock):
    s = space.book_series("big", "alice", dt(20, 10), dt(20, 11), count=3)
    clock.t = dt(19, 10)
    assert [r.fee for r in space.cancel_series(s.id)] == [3, 0, 0]
    assert [n.text for n in space.notifications("alice")][0] == f"예약 {s.booking_ids[0]} 취소 · 수수료 3 · 환불 7"


def test_cli_cancel_new_table(tmp_path):
    db = tmp_path / "b.json"
    env = dict(os.environ, PYTHONIOENCODING="utf-8")

    def cli(now, *args):
        return subprocess.run([sys.executable, "-m", "booking", "--db", str(db), "--now", now, *args],
                              capture_output=True, text=True, encoding="utf-8", env=env)

    assert cli("2026-10-19T09:00", "resource-add", "big", "Big", "--capacity", "8", "--cph", "10").returncode == 0
    assert cli("2026-10-19T09:00", "member-add", "alice", "Alice", "--plan", "pro").returncode == 0
    assert cli("2026-10-19T09:00", "book", "big", "alice", "2026-10-21T08:00", "2026-10-21T09:00").returncode == 0
    r = cli("2026-10-19T09:30", "cancel", "1")
    assert r.returncode == 0 and r.stdout.strip() == "1\t3\t7"
    r = cli("2026-10-19T09:30", "invoice", "alice", "2026-10")
    assert "2026-10-21\t취소 수수료 Big 08:00-09:00\t3" in r.stdout.splitlines()
