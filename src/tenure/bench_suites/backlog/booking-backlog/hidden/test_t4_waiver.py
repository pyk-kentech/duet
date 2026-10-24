"""#4 대기자가 자리를 이어받으면 취소 수수료 면제."""

from datetime import date, datetime

import pytest

from booking import Space
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
def clock():
    return Clock(NOW)


@pytest.fixture
def space(clock):
    s = Space(clock=clock)
    s.add_resource("room-a", "Room A", capacity=6, credits_per_hour=4)
    s.add_resource("room-b", "Room B", capacity=10, credits_per_hour=6, buffer_minutes=15)
    s.add_resource("big", "Big", capacity=8, credits_per_hour=10)
    s.add_member("alice", "Alice", plan="pro")
    s.add_member("bob", "Bob", plan="pro")
    s.add_member("carol", "Carol")                      # basic 40
    return s


def _taken_over(space, clock, wait_start=(19, 14), wait_end=(19, 15)):
    """alice 월 14~15 (big), bob 대기, 13:00 에 취소(원래 100%)."""
    b = space.book("big", "alice", dt(19, 14), dt(19, 15))
    space.join_waitlist("big", "bob", dt(*wait_start), dt(*wait_end))
    clock.t = dt(19, 13)
    return b, space.cancel(b.id)


def test_waiver_result_and_balance(space, clock):
    b, c = _taken_over(space, clock)
    assert (c.fee, c.refund, b.fee) == (0, 10, 0)
    assert space.balance("alice", "2026-10") == 120


def test_waiver_promoted_member_is_charged(space, clock):
    _taken_over(space, clock)
    [nb] = space.bookings(member_id="bob")
    assert nb.note == "waitlist" and space.balance("bob", "2026-10") == 110


def test_waiver_notification_and_invoice(space, clock):
    b, _c = _taken_over(space, clock)
    assert [n.text for n in space.notifications("alice") if n.kind == "cancelled"] == \
        [f"예약 {b.id} 취소 · 수수료 0 · 환불 10"]
    assert invoice(space, "alice", "2026-10").lines == []


def test_partially_overlapping_promotion_waives(space, clock):
    _b, c = _taken_over(space, clock, wait_start=(19, 14, 30), wait_end=(19, 15, 30))
    assert c.fee == 0


def test_waiver_beats_half_and_quarter_fee(space, clock):
    a = space.book("big", "alice", dt(20, 10), dt(20, 11))
    b = space.book("big", "alice", dt(21, 10), dt(21, 11))
    space.join_waitlist("big", "bob", dt(20, 10), dt(20, 11))
    space.join_waitlist("big", "bob", dt(21, 10), dt(21, 11))
    clock.t = dt(19, 14)                                       # 20시간 전(50%), 44시간 전(25%)
    assert (space.cancel(a.id).fee, space.cancel(b.id).fee) == (0, 0)


def test_buffer_blocked_promotion_keeps_fee(space, clock):
    space.book("room-b", "alice", dt(19, 13), dt(19, 14))
    y = space.book("room-b", "alice", dt(19, 14), dt(19, 15))
    space.join_waitlist("room-b", "bob", dt(19, 14), dt(19, 15))
    clock.t = dt(19, 13, 30)
    c = space.cancel(y.id)
    assert (c.fee, c.refund) == (6, 0)
    assert len(space.waitlist()) == 1 and space.bookings(member_id="bob") == []


def test_skipped_for_credits_keeps_fee(space, clock):
    space.book("big", "carol", dt(20, 9), dt(20, 12))           # 30
    space.book("room-a", "carol", dt(20, 13), dt(20, 14))       # 4 → 잔액 6
    b = space.book("big", "alice", dt(19, 14), dt(19, 15))
    space.join_waitlist("big", "carol", dt(19, 14), dt(19, 15))
    clock.t = dt(19, 13)
    assert space.cancel(b.id).fee == 10
    assert [e.member_id for e in space.waitlist()] == ["carol"]


def test_promotion_outside_cancelled_time_keeps_fee(space, clock):
    b = space.book("room-b", "alice", dt(20, 10), dt(20, 11))
    space.join_waitlist("room-b", "bob", dt(20, 11), dt(20, 12))    # 버퍼 때문에만 막힘
    clock.t = dt(20, 9)
    c = space.cancel(b.id)
    assert [x.start for x in space.bookings(member_id="bob")] == [dt(20, 11)]
    assert (c.fee, c.refund) == (6, 0)


def test_series_cancel_waives_taken_occurrence(space, clock):
    s = space.book_series("big", "alice", dt(19, 14), dt(19, 15), count=2)
    space.join_waitlist("big", "bob", dt(19, 14), dt(19, 15))
    clock.t = dt(19, 13)
    assert [(r.fee, r.refund) for r in space.cancel_series(s.id)] == [(0, 10), (0, 10)]
    assert [n.text for n in space.notifications("alice")][0] == f"예약 {s.booking_ids[0]} 취소 · 수수료 0 · 환불 10"


def test_series_cancel_waiver_is_per_occurrence(space, clock):
    s = space.book_series("big", "alice", dt(19, 14), dt(19, 15), count=2)
    space.join_waitlist("big", "bob", dt(26, 14), dt(26, 15))
    clock.t = dt(19, 13)
    assert [(r.fee, r.refund) for r in space.cancel_series(s.id)] == [(10, 0), (0, 10)]


def test_skip_occurrence_waiver(space, clock):
    s = space.book_series("big", "alice", dt(19, 14), dt(19, 15), count=2)
    space.join_waitlist("big", "bob", dt(19, 14), dt(19, 15))
    clock.t = dt(19, 13)
    c = space.skip_occurrence(s.id, date(2026, 10, 19))
    assert (c.fee, c.refund) == (0, 10) and space.balance("alice", "2026-10") == 110
