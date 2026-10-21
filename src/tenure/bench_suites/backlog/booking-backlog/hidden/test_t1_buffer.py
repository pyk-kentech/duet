"""#1 버퍼 규칙이 모든 경로에서 같아야 한다."""

from datetime import date, datetime

import pytest

from booking import BookingError, Conflict, Space

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
    return s


@pytest.fixture
def busy(space):
    """room-b: alice 화 10:00~11:00."""
    space.book("room-b", "alice", dt(20, 10), dt(20, 11))
    return space


# ---------------------------------------------------------------- 반복 예약
def test_series_conflicts_with_buffer(busy):
    with pytest.raises(Conflict):
        busy.book_series("room-b", "bob", dt(20, 11), dt(20, 12), count=2)
    assert len(busy.bookings()) == 1 and busy.all_series() == []


def test_series_skip_conflicts_skips_buffer_violation(busy):
    s = busy.book_series("room-b", "bob", dt(20, 11), dt(20, 12), count=2, skip_conflicts=True)
    assert s.exceptions == {date(2026, 10, 20)}
    assert [busy.booking(i).start for i in s.booking_ids] == [dt(27, 11)]


def test_series_same_member_back_to_back(busy):
    s = busy.book_series("room-b", "alice", dt(20, 11), dt(20, 12), count=2)
    assert len(s.booking_ids) == 2


def test_series_exact_buffer_gap(busy):
    s = busy.book_series("room-b", "bob", dt(20, 11, 15), dt(20, 12), count=2)
    assert len(s.booking_ids) == 2


# ---------------------------------------------------------------- 예약 변경
def test_move_into_buffer_after(busy):
    mine = busy.book("room-b", "bob", dt(20, 14), dt(20, 15))
    with pytest.raises(Conflict):
        busy.move(mine.id, dt(20, 11), dt(20, 12))
    assert (mine.start, mine.end) == (dt(20, 14), dt(20, 15))


def test_move_into_buffer_before(busy):
    mine = busy.book("room-b", "bob", dt(20, 14), dt(20, 15))
    with pytest.raises(Conflict):
        busy.move(mine.id, dt(20, 8, 30), dt(20, 9, 50))


def test_move_exact_buffer_gap(busy):
    mine = busy.book("room-b", "bob", dt(20, 14), dt(20, 15))
    busy.move(mine.id, dt(20, 11, 15), dt(20, 12))
    assert mine.start == dt(20, 11, 15)


def test_move_same_member_back_to_back(busy):
    own = busy.book("room-b", "alice", dt(20, 16), dt(20, 17))
    busy.move(own.id, dt(20, 9), dt(20, 10))
    assert own.start == dt(20, 9)


# ---------------------------------------------------------------- 대기 등록
def test_join_waitlist_when_only_buffer_blocks(busy):
    e = busy.join_waitlist("room-b", "bob", dt(20, 11), dt(20, 12))
    assert [x.id for x in busy.waitlist("room-b")] == [e.id]


def test_join_waitlist_rejects_bookable_time(busy):
    with pytest.raises(BookingError):
        busy.join_waitlist("room-b", "alice", dt(20, 11), dt(20, 12))       # 같은 회원은 바로 예약할 수 있다
    with pytest.raises(BookingError):
        busy.join_waitlist("room-b", "bob", dt(20, 11, 15), dt(20, 12))
    assert busy.waitlist() == []


# ---------------------------------------------------------------- 대기자 승격
def test_promotion_does_not_break_buffer(space, clock):
    space.book("room-b", "alice", dt(20, 9), dt(20, 10))
    target = space.book("room-b", "alice", dt(20, 10), dt(20, 11))
    entry = space.join_waitlist("room-b", "bob", dt(20, 10), dt(20, 11))
    clock.t = dt(19, 10)
    space.cancel(target.id)
    assert space.bookings(member_id="bob") == [] and [x.id for x in space.waitlist()] == [entry.id]


def test_promotion_with_exact_gap(space, clock):
    space.book("room-b", "alice", dt(20, 9), dt(20, 9, 45))
    t1 = space.book("room-b", "alice", dt(20, 10), dt(20, 11))
    space.join_waitlist("room-b", "bob", dt(20, 10), dt(20, 11))
    clock.t = dt(19, 10)
    space.cancel(t1.id)
    assert [b.start for b in space.bookings(member_id="bob")] == [dt(20, 10)]


def test_promotion_same_member_back_to_back(space, clock):
    space.book("room-b", "bob", dt(21, 9), dt(21, 10))
    t2 = space.book("room-b", "alice", dt(21, 10, 15), dt(21, 11, 15))
    space.join_waitlist("room-b", "bob", dt(21, 10), dt(21, 11))
    clock.t = dt(19, 10)
    space.cancel(t2.id)
    assert [b.start for b in space.bookings(member_id="bob")] == [dt(21, 9), dt(21, 10)]


# ---------------------------------------------------------------- 빈 시각
def test_free_slots_exclude_buffer_zone(busy):
    slots = busy.free_slots("room-b", date(2026, 10, 20), 60)
    for bad in (dt(20, 9), dt(20, 9, 30), dt(20, 10, 45), dt(20, 11)):
        assert bad not in slots


def test_free_slots_full_list(busy):
    slots = busy.free_slots("room-b", date(2026, 10, 20), 60)
    assert slots[:5] == [dt(20, 8), dt(20, 8, 15), dt(20, 8, 30), dt(20, 8, 45), dt(20, 11, 15)]
    assert len(slots) == 4 + 32
