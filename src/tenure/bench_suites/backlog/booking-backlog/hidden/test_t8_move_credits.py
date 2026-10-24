"""#8 예약 변경 때 크레딧 다시 계산."""

import os
import subprocess
import sys
from datetime import datetime

import pytest

from booking import InsufficientCredits, Space
from booking.invoices import invoice

NOW = datetime(2026, 10, 19, 9, 0)      # 월요일


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def dt(day, hh, mm=0, month=10):
    return datetime(2026, month, day, hh, mm)


@pytest.fixture
def space():
    s = Space(clock=Clock(NOW))
    s.add_resource("room-a", "Room A", capacity=6, credits_per_hour=4)
    s.add_member("alice", "Alice", plan="pro")
    s.add_member("carol", "Carol")                      # basic 40, 초과 불가
    return s


def entries(space, member):
    return [(e.kind, e.credits, e.month, e.note) for e in space.ledger(member)]


# ---------------------------------------------------------------- 같은 달
def test_extend_charges_difference(space):
    b = space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    space.move(b.id, dt(20, 10), dt(20, 13))
    assert b.charged == 12 and space.balance("alice", "2026-10") == 108


def test_extend_ledger_entry(space):
    b = space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    space.move(b.id, dt(20, 10), dt(20, 13))
    assert entries(space, "alice") == [("charge", 4, "2026-10", "booking"), ("charge", 8, "2026-10", "move")]


def test_shorten_refunds_difference(space):
    b = space.book("room-a", "alice", dt(20, 10), dt(20, 13))
    space.move(b.id, dt(20, 14), dt(20, 15))
    assert b.charged == 4 and space.balance("alice", "2026-10") == 116
    assert entries(space, "alice")[-1] == ("refund", 8, "2026-10", "move")


def test_same_cost_adds_no_ledger_entry(space):
    b = space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    space.move(b.id, dt(21, 14), dt(21, 15))
    assert len(space.ledger("alice")) == 1 and b.charged == 4


def test_off_peak_price_is_recomputed(space):
    b = space.book("room-a", "alice", dt(20, 16), dt(20, 17))          # 4
    space.move(b.id, dt(20, 18), dt(20, 19))                           # 비수기: 2
    assert b.charged == 2 and space.balance("alice", "2026-10") == 118


# ---------------------------------------------------------------- 잔액 검사
@pytest.fixture
def tight(space):
    """carol: 10월 잔액 4 인 상태에서 수 10:00~11:00(4) 예약."""
    space.book("room-a", "carol", dt(20, 8), dt(20, 16))               # 32
    return space.book("room-a", "carol", dt(21, 10), dt(21, 11))       # 4 → 잔액 4


def test_difference_fits_balance(space, tight):
    space.move(tight.id, dt(21, 10), dt(21, 12))                       # 차액 4 = 잔액 4
    assert tight.charged == 8 and space.balance("carol", "2026-10") == 0


def test_difference_over_balance_changes_nothing(space, tight):
    space.move(tight.id, dt(21, 10), dt(21, 12))
    before = list(space.ledger("carol"))
    with pytest.raises(InsufficientCredits):
        space.move(tight.id, dt(21, 14), dt(21, 16, 15))               # 차액 1 > 잔액 0
    assert (tight.start, tight.end, tight.charged) == (dt(21, 10), dt(21, 12), 8)
    assert space.ledger("carol") == before


# ---------------------------------------------------------------- 다른 달
def test_cross_month_refunds_old_month(space):
    b = space.book("room-a", "alice", dt(30, 10), dt(30, 11))
    space.move(b.id, dt(2, 10, month=11), dt(2, 12, month=11))
    assert space.balance("alice", "2026-10") == 120


def test_cross_month_charges_new_month(space):
    b = space.book("room-a", "alice", dt(30, 10), dt(30, 11))
    space.move(b.id, dt(2, 10, month=11), dt(2, 12, month=11))
    assert space.balance("alice", "2026-11") == 112


def test_cross_month_ledger_entries(space):
    b = space.book("room-a", "alice", dt(30, 10), dt(30, 11))
    space.move(b.id, dt(2, 10, month=11), dt(2, 12, month=11))
    assert entries(space, "alice")[1:] == [("refund", 4, "2026-10", "move"), ("charge", 8, "2026-11", "move")]


def test_cross_month_checks_new_month_balance(space):
    b = space.book("room-a", "carol", dt(30, 10), dt(30, 11))          # 10월 4
    space.book("room-a", "carol", dt(2, 8, month=11), dt(2, 17, 30, month=11))     # 11월 38 → 잔액 2
    with pytest.raises(InsufficientCredits):
        space.move(b.id, dt(3, 10, month=11), dt(3, 11, month=11))     # 같은 비용이어도 11월 잔액 2 < 4
    assert b.start == dt(30, 10) and space.balance("carol", "2026-10") == 36
    assert space.balance("carol", "2026-11") == 2


def test_cross_month_same_cost_still_moves_credits(space):
    b = space.book("room-a", "carol", dt(30, 10), dt(30, 11))
    space.move(b.id, dt(3, 10, month=11), dt(3, 11, month=11))
    assert space.balance("carol", "2026-10") == 40 and space.balance("carol", "2026-11") == 36


def test_invoices_follow_the_move(space):
    b = space.book("room-a", "alice", dt(30, 10), dt(30, 11))
    space.move(b.id, dt(2, 10, month=11), dt(2, 11, 30, month=11))
    assert invoice(space, "alice", "2026-10").lines == []
    nov = invoice(space, "alice", "2026-11")
    assert [(line.text, line.credits) for line in nov.lines] == [("Room A 10:00-11:30", 6)] and nov.used == 6


def test_cli_move_prints_new_credits(tmp_path):
    db = tmp_path / "b.json"
    env = dict(os.environ, PYTHONIOENCODING="utf-8")

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "booking", "--db", str(db), "--now", "2026-10-19T09:00", *args],
                              capture_output=True, text=True, encoding="utf-8", env=env)

    assert cli("resource-add", "room-a", "Room A", "--capacity", "6").returncode == 0
    assert cli("member-add", "alice", "Alice").returncode == 0
    assert cli("book", "room-a", "alice", "2026-10-20T10:00", "2026-10-20T11:00").returncode == 0
    r = cli("move", "1", "2026-10-20T10:00", "2026-10-20T12:00")
    assert r.stdout.strip() == "1\t2026-10-20T10:00\t2026-10-20T12:00\t8"
    assert cli("balance", "alice").stdout.strip() == "alice\t2026-10\t40\t8\t32"
