from datetime import datetime, timedelta

import pytest

from booking import PLANS
from booking.credits import cost


def dt(day, hh, mm=0):
    return datetime(2026, 10, day, hh, mm)


def test_plans():
    assert PLANS["basic"].monthly_credits == 40 and PLANS["basic"].overage_price is None
    assert str(PLANS["pro"].overage_price) == "2.00"


def test_cost(space):
    a = space.resource("room-a")
    assert cost(a, dt(20, 10), dt(20, 11)) == 4
    assert cost(a, dt(20, 10), dt(20, 11, 30)) == 6
    assert cost(space.resource("desk-1"), dt(20, 10), dt(20, 10, 15)) == 1      # 0.25 → 1


def test_balance_after_booking(space):
    space.book("room-a", "alice", dt(20, 10), dt(20, 12))
    assert space.balance("alice", "2026-10") == 32
    assert space.balance("alice", "2026-11") == 40


def test_free_cancellation_refunds_all(space, clock):
    b = space.book("room-a", "alice", dt(21, 10), dt(21, 12))
    c = space.cancel(b.id)
    assert (c.fee, c.refund) == (0, 8)
    assert space.balance("alice", "2026-10") == 40
    assert b.fee == 0 and b.cancelled_at == clock.t


def test_late_cancellation_full_fee(space, clock):
    b = space.book("room-a", "alice", dt(19, 10), dt(19, 12))
    clock.t = dt(19, 9, 30)
    c = space.cancel(b.id)
    assert (c.fee, c.refund) == (8, 0)
    assert space.balance("alice", "2026-10") == 32


def test_half_fee(space, clock):
    b = space.book("room-a", "alice", dt(20, 10), dt(20, 12))
    clock.t = dt(20, 0)
    assert space.cancel(b.id).fee == 4


def test_cannot_cancel_started(space, clock):
    b = space.book("room-a", "alice", dt(20, 10), dt(20, 12))
    clock.t = dt(20, 10)
    with pytest.raises(Exception):
        space.cancel(b.id)


def test_ledger_entries(space):
    b = space.book("room-a", "alice", dt(21, 10), dt(21, 11))
    space.cancel(b.id)
    kinds = [(e.kind, e.credits, e.booking_id, e.month) for e in space.ledger("alice")]
    assert kinds == [("charge", 4, b.id, "2026-10"), ("refund", 4, b.id, "2026-10")]


def test_set_plan(space):
    space.set_plan("alice", "pro")
    assert space.plan_of("alice").name == "pro"
    with pytest.raises(ValueError):
        space.set_plan("alice", "gold")
