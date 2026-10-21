"""기존 동작이 그대로인지: 비용·크레딧 달·수수료 올림·청구서·알림."""

from datetime import datetime

import pytest

from booking import BookingError, Space
from booking.credits import cost
from booking.invoices import invoice, render_invoice
from booking.reports import credit_usage

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
    s.add_resource("small", "Small", capacity=2, credits_per_hour=3)
    s.add_member("alice", "Alice", plan="pro")
    s.add_member("carol", "Carol")                      # basic
    s.add_member("dave", "Dave", plan="payg")
    return s


def test_cost_rounding_and_off_peak_by_start(space):
    a, small = space.resource("room-a"), space.resource("small")
    assert cost(small, dt(20, 10), dt(20, 10, 45)) == 3             # 2.25 → 3
    assert cost(a, dt(20, 17, 30), dt(20, 19)) == 6                 # 시작이 18시 전: 정가
    assert cost(a, dt(20, 18), dt(20, 19, 30)) == 3                 # 18시 시작: 절반
    assert cost(a, dt(24, 10), dt(24, 11, 30)) == 3                 # 토요일: 절반
    assert cost(a, dt(20, 6, 45), dt(20, 7, 15)) == 1               # 7시 전 시작: 절반, 올림


def test_half_fee_rounds_up(space, clock):
    b = space.book("small", "alice", dt(20, 10), dt(20, 11))        # 3
    clock.t = dt(19, 20)                                            # 14시간 전
    c = space.cancel(b.id)
    assert (c.fee, c.refund) == (2, 1)
    assert space.balance("alice", "2026-10") == 118


def test_full_fee_under_two_hours(space, clock):
    b = space.book("room-a", "alice", dt(19, 12), dt(19, 13))
    clock.t = dt(19, 10, 1)
    c = space.cancel(b.id)
    assert (c.fee, c.refund) == (4, 0) and b.fee == 4 and b.cancelled_at == dt(19, 10, 1)
    assert [n.text for n in space.notifications("alice")] == [f"예약 {b.id} 취소 · 수수료 4 · 환불 0"]
    assert [(e.kind, e.credits) for e in space.ledger("alice")] == [("charge", 4)]


def test_cannot_cancel_started_or_twice(space, clock):
    a = space.book("room-a", "alice", dt(19, 12), dt(19, 13))
    b = space.book("room-a", "alice", dt(23, 12), dt(23, 13))
    space.cancel(b.id)
    with pytest.raises(BookingError):
        space.cancel(b.id)
    clock.t = dt(19, 12)
    with pytest.raises(BookingError):
        space.cancel(a.id)


def test_refund_goes_to_booking_month(space, clock):
    b = space.book("room-a", "alice", dt(2, 10, month=11), dt(2, 11, month=11))
    assert space.balance("alice", "2026-10") == 120 and space.balance("alice", "2026-11") == 116
    clock.t = dt(19, 10)
    space.cancel(b.id)
    assert space.balance("alice", "2026-11") == 120
    assert [(e.kind, e.month) for e in space.ledger("alice")] == [("charge", "2026-11"), ("refund", "2026-11")]


def test_payg_invoice_render(space, clock):
    late = space.book("room-a", "dave", dt(19, 14), dt(19, 15))
    space.book("room-b", "dave", dt(20, 9), dt(20, 11))
    clock.t = dt(19, 13, 30)
    space.cancel(late.id)
    assert render_invoice(invoice(space, "dave", "2026-10")) == (
        "청구서 2026-10 · dave (payg)\n"
        "2026-10-19\t취소 수수료 Room A 14:00-15:00\t4\n"
        "2026-10-20\tRoom B 09:00-11:00\t12\n"
        "사용 16 / 할당 0\n"
        "초과 16 크레딧 · 금액 48.00\n")


def test_set_plan_changes_allowance(space):
    space.book("room-a", "carol", dt(20, 10), dt(20, 17, 30))      # 30
    space.set_plan("carol", "pro")
    assert space.balance("carol", "2026-10") == 90
    row = [r for r in credit_usage(space, "2026-10") if r.member_id == "carol"][0]
    assert (row.plan, row.allowance, row.used, row.balance) == ("pro", 120, 30, 90)


def test_cancel_series_only_future(space, clock):
    s = space.book_series("room-a", "alice", dt(19, 10), dt(19, 11), count=3)
    clock.t = dt(19, 10, 30)
    done = space.cancel_series(s.id)
    assert [r.booking_id for r in done] == s.booking_ids[1:] and space.booking(s.booking_ids[0]).active
