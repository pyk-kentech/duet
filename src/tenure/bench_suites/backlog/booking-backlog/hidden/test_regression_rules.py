"""기존 동작(README·docstring 에 적힌 규칙)이 그대로인지: 예약·충돌·버퍼·변경·반복·대기열."""

from datetime import date, datetime

import pytest

from booking import BookingError, Conflict, InsufficientCredits, OutsideHours, PolicyError, Space

NOW = datetime(2026, 10, 19, 9, 0)      # 월요일


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def dt(day, hh, mm=0, month=10, ss=0):
    return datetime(2026, month, day, hh, mm, ss)


@pytest.fixture
def clock():
    return Clock(NOW)


@pytest.fixture
def space(clock):
    s = Space(clock=clock)
    s.add_resource("room-a", "Room A", capacity=6, credits_per_hour=4)
    s.add_resource("room-b", "Room B", capacity=10, credits_per_hour=6, buffer_minutes=15)
    s.add_resource("desk-1", "Desk 1", kind="desk", credits_per_hour=1, hours="mon-sat 07:00-22:00")
    s.add_member("alice", "Alice", plan="pro")
    s.add_member("bob", "Bob", plan="pro")
    s.add_member("carol", "Carol")                      # basic
    return s


# ---------------------------------------------------------------- 충돌·버퍼
def test_touching_bookings_are_not_a_conflict(space):
    space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    space.book("room-a", "bob", dt(20, 11), dt(20, 12))
    space.book("room-a", "carol", dt(20, 9), dt(20, 10))
    assert len(space.bookings()) == 3


def test_buffer_room_same_member_back_to_back(space):
    space.book("room-b", "alice", dt(20, 10), dt(20, 11))
    space.book("room-b", "alice", dt(20, 11), dt(20, 12))
    space.book("room-b", "alice", dt(20, 9), dt(20, 10))
    with pytest.raises(Conflict):
        space.book("room-b", "alice", dt(20, 11, 30), dt(20, 12, 30))      # 같은 회원도 겹치면 안 됨


def test_buffer_exact_gap_on_both_sides(space):
    space.book("room-b", "alice", dt(20, 10), dt(20, 11))
    space.book("room-b", "bob", dt(20, 11, 15), dt(20, 12))
    space.book("room-b", "carol", dt(20, 8, 45), dt(20, 9, 45))
    assert len(space.bookings(resource_id="room-b")) == 3


def test_buffer_does_not_shrink_opening_hours(space):
    a = space.book("room-b", "alice", dt(20, 19), dt(20, 20))       # 영업 종료 시각까지
    b = space.book("room-b", "bob", dt(21, 8), dt(21, 9))            # 영업 시작 시각부터
    s = space.book_series("room-b", "carol", dt(22, 19), dt(22, 20), count=2)
    assert (a.end, b.start, len(s.booking_ids)) == (dt(20, 20), dt(21, 8), 2)


def test_series_and_move_touching_without_buffer(space):
    space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    s = space.book_series("room-a", "bob", dt(20, 11), dt(20, 12), count=2)
    other = space.book("room-a", "carol", dt(20, 14), dt(20, 15))
    space.move(other.id, dt(20, 9), dt(20, 10))
    assert len(s.booking_ids) == 2 and other.start == dt(20, 9)


def test_waitlist_touching_without_buffer_is_bookable(space):
    space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    with pytest.raises(BookingError):
        space.join_waitlist("room-a", "bob", dt(20, 11), dt(20, 12))


# ---------------------------------------------------------------- 시각
def test_slot_rounding_with_seconds(space):
    b = space.book("room-a", "alice", dt(20, 10, 14, ss=59), dt(20, 11, 0, ss=1))
    assert (b.start, b.end, b.charged) == (dt(20, 10), dt(20, 11, 15), 5)


def test_past_check_uses_rounded_start(space, clock):
    clock.t = dt(19, 9, 7)
    with pytest.raises(ValueError):
        space.book("room-a", "alice", dt(19, 9, 10), dt(19, 10))     # 내리면 09:00 < 09:07
    space.book("room-a", "alice", dt(19, 9, 15), dt(19, 10))


def test_booking_cannot_cross_midnight_on_normal_hours(space):
    with pytest.raises(OutsideHours):
        space.book("desk-1", "alice", dt(20, 21), dt(20, 23))
    with pytest.raises(OutsideHours):
        space.book("room-a", "alice", dt(20, 19), dt(20, 20, 15))


# ---------------------------------------------------------------- 예약 변경
def test_move_keeps_id_series_and_created_at(space, clock):
    s = space.book_series("room-a", "alice", dt(20, 10), dt(20, 11), count=2)
    b = space.booking(s.booking_ids[0])
    clock.t = dt(19, 10)
    moved = space.move(b.id, dt(20, 14), dt(20, 15))
    assert moved is b and (b.id, b.series_id, b.created_at) == (s.booking_ids[0], s.id, NOW)
    assert space.booking(b.id) is b and b.id in s.booking_ids and len(space.bookings(include_cancelled=True)) == 2


def test_move_has_no_fee_or_notification(space, clock):
    b = space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    clock.t = dt(20, 9)                                              # 취소라면 수수료 100% 시점
    space.move(b.id, dt(20, 14), dt(20, 15))
    assert b.active and b.fee is None and space.notifications("alice") == []
    assert space.balance("alice", "2026-10") == 116


def test_move_does_not_promote_waitlist(space, clock):
    b = space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    space.join_waitlist("room-a", "bob", dt(20, 10), dt(20, 11))
    clock.t = dt(19, 12)
    space.move(b.id, dt(20, 14), dt(20, 15))
    assert len(space.waitlist()) == 1 and space.bookings(member_id="bob") == []    # 알려진 제약


# ---------------------------------------------------------------- 반복 예약
def test_series_on_closed_day(space):
    with pytest.raises(OutsideHours):
        space.book_series("room-a", "bob", dt(24, 10), dt(24, 11), count=2)                       # 토요일
    with pytest.raises(BookingError):
        space.book_series("room-a", "bob", dt(24, 10), dt(24, 11), count=2, skip_conflicts=True)  # 만들 발생 없음
    assert space.all_series() == []


def test_series_credit_check_is_all_or_nothing(space):
    space.add_resource("big", "Big", capacity=8, credits_per_hour=10)
    with pytest.raises(InsufficientCredits):
        space.book_series("big", "carol", dt(20, 10), dt(20, 12, 15), count=3, skip_conflicts=True)  # 10월: 23+23 > 40
    assert space.bookings() == [] and space.balance("carol", "2026-10") == 40


def test_series_advance_limit_only_first_occurrence(space):
    s = space.book_series("room-a", "carol", dt(20, 10), dt(20, 11), count=8)    # basic 30일, 마지막은 49일 뒤
    assert len(s.booking_ids) == 8
    with pytest.raises(PolicyError):
        space.book_series("room-a", "carol", dt(20, 10, month=11), dt(20, 11, month=11), count=1)


# ---------------------------------------------------------------- 대기열
def test_waitlist_fifo_skip_and_expiry(space, clock):
    space.add_resource("big", "Big", capacity=8, credits_per_hour=10)
    space.book("big", "carol", dt(21, 9), dt(21, 12, 30))           # carol 잔액 5
    early = space.book("big", "alice", dt(19, 10), dt(19, 11))
    space.join_waitlist("big", "bob", dt(19, 10), dt(19, 11))       # 승격 전에 시작이 지나 지워진다
    b = space.book("big", "alice", dt(20, 10), dt(20, 11))
    space.join_waitlist("big", "carol", dt(20, 10), dt(20, 11))
    second = space.join_waitlist("big", "bob", dt(20, 10), dt(20, 11))
    clock.t = dt(19, 10, 30)
    space.cancel(b.id)
    assert [(x.member_id, x.start) for x in space.bookings(resource_id="big", start=dt(20, 0), end=dt(21, 0))] == \
        [("bob", dt(20, 10))]
    assert [(e.member_id, e.start) for e in space.waitlist()] == [("carol", dt(20, 10))]
    assert early.active and second.id not in [e.id for e in space.waitlist()]


def test_promoted_booking_details(space, clock):
    b = space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    e = space.join_waitlist("room-a", "bob", dt(20, 10), dt(20, 11), attendees=3)
    clock.t = dt(19, 12)
    space.cancel(b.id)
    [nb] = space.bookings(member_id="bob")
    assert (nb.note, nb.created_at, nb.attendees, nb.charged) == ("waitlist", dt(19, 12), 3, 4)
    [n] = space.notifications("bob")
    assert (n.kind, n.text) == ("promoted", f"대기 {e.id} → 예약 {nb.id} (room-a 2026-10-20T10:00~2026-10-20T11:00)")


def test_promotion_ignores_advance_limit(space, clock):
    b = space.book("room-a", "alice", dt(17, 10, month=11), dt(17, 11, month=11))
    space.join_waitlist("room-a", "carol", dt(17, 10, month=11), dt(17, 11, month=11))
    clock.t = dt(19, 10)
    space.set_plan("carol", "payg")                                  # 이제 14일 한도지만 승격은 다시 보지 않는다
    space.cancel(b.id)
    assert [x.member_id for x in space.bookings(resource_id="room-a")] == ["carol"]


# ---------------------------------------------------------------- 기타
def test_update_resource_keeps_existing_bookings(space):
    b = space.book("room-a", "alice", dt(20, 18), dt(20, 20))
    space.update_resource("room-a", hours="mon-fri 09:00-17:00", buffer_minutes=30)
    assert b.active and space.resource("room-a").buffer_minutes == 30
    with pytest.raises(OutsideHours):
        space.book("room-a", "bob", dt(21, 18), dt(21, 19))


def test_free_slots_skip_past_times_and_round_minutes(space, clock):
    clock.t = dt(19, 18, 10)
    assert space.free_slots("room-a", date(2026, 10, 19), 50) == [dt(19, 18, 15), dt(19, 18, 30), dt(19, 18, 45),
                                                                   dt(19, 19)]


def test_bookings_order_and_window(space, clock):
    c = space.book("room-b", "carol", dt(20, 9), dt(20, 10))
    a = space.book("room-a", "alice", dt(20, 9), dt(20, 10))
    b = space.book("room-a", "bob", dt(20, 10), dt(20, 11))
    space.cancel(a.id)
    assert [x.id for x in space.bookings(include_cancelled=True)] == [c.id, a.id, b.id]       # 시작, id 순
    assert [x.id for x in space.bookings(start=dt(20, 10), end=dt(20, 12))] == [b.id]
    assert [x.id for x in space.bookings(resource_id="room-a", start=dt(20, 9), end=dt(20, 9, 30),
                                         include_cancelled=True)] == [a.id]


def test_ledger_keeps_record_order(space, clock):
    a = space.book("room-a", "alice", dt(22, 10), dt(22, 11))
    space.book("room-a", "bob", dt(22, 11), dt(22, 12))
    space.cancel(a.id)
    assert [(e.member_id, e.kind) for e in space.ledger()] == [("alice", "charge"), ("bob", "charge"),
                                                               ("alice", "refund")]
