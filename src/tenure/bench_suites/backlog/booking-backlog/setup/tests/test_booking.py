from datetime import datetime, timedelta

import pytest

from booking import (
    AlreadyExists, BookingError, CapacityExceeded, Conflict, InsufficientCredits, OutsideHours, PolicyError,
    UnknownBooking, UnknownMember, UnknownResource,
)


def dt(day, hh, mm=0):
    return datetime(2026, 10, day, hh, mm)


def test_book_basic(space):
    b = space.book("room-a", "alice", dt(20, 10), dt(20, 11, 30), attendees=4, note="주간 회의")
    assert (b.id, b.resource_id, b.member_id, b.attendees, b.note) == (1, "room-a", "alice", 4, "주간 회의")
    assert b.active and b.charged == 6 and b.created_at == datetime(2026, 10, 19, 9, 0)
    assert space.booking(1) is b


def test_ids_increase(space):
    a = space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    b = space.book("room-a", "alice", dt(20, 12), dt(20, 13))
    assert (a.id, b.id) == (1, 2)


def test_slot_rounding(space):
    b = space.book("room-a", "alice", dt(20, 10, 5), dt(20, 10, 50))
    assert (b.start, b.end) == (dt(20, 10), dt(20, 11))


def test_overlap_is_conflict(space):
    space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    with pytest.raises(Conflict):
        space.book("room-a", "bob", dt(20, 10, 30), dt(20, 11, 30))


def test_other_resource_no_conflict(space):
    space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    space.book("room-b", "bob", dt(20, 10), dt(20, 11))


def test_buffer_blocks_other_member(space):
    space.book("room-b", "alice", dt(20, 10), dt(20, 11))
    with pytest.raises(Conflict):
        space.book("room-b", "bob", dt(20, 11), dt(20, 12))
    space.book("room-b", "bob", dt(20, 11, 15), dt(20, 12))


def test_cancelled_does_not_block(space):
    b = space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    space.cancel(b.id)
    space.book("room-a", "bob", dt(20, 10), dt(20, 11))


def test_outside_hours(space):
    with pytest.raises(OutsideHours):
        space.book("room-a", "alice", dt(20, 7), dt(20, 9))
    with pytest.raises(OutsideHours):
        space.book("room-a", "alice", dt(24, 10), dt(24, 11))       # 토요일


def test_capacity(space):
    with pytest.raises(CapacityExceeded):
        space.book("room-a", "alice", dt(20, 10), dt(20, 11), attendees=7)
    with pytest.raises(CapacityExceeded):
        space.book("desk-1", "alice", dt(20, 10), dt(20, 11), attendees=2)


def test_bad_values(space):
    with pytest.raises(ValueError):
        space.book("room-a", "alice", dt(20, 11), dt(20, 10))
    with pytest.raises(ValueError):
        space.book("room-a", "alice", "2026-10-20T10:00", dt(20, 11))
    with pytest.raises(ValueError):
        space.book("room-a", "alice", dt(19, 7), dt(19, 8))           # 지난 시각
    with pytest.raises(ValueError):
        space.book("room-a", "alice", dt(20, 8), dt(20, 20, 15))      # 12시간 초과


def test_unknown_things(space):
    with pytest.raises(UnknownResource):
        space.book("nope", "alice", dt(20, 10), dt(20, 11))
    with pytest.raises(UnknownMember):
        space.book("room-a", "nope", dt(20, 10), dt(20, 11))
    with pytest.raises(UnknownBooking):
        space.cancel(99)


def test_duplicate_resource_and_member(space):
    with pytest.raises(AlreadyExists):
        space.add_resource("room-a", "Again")
    with pytest.raises(AlreadyExists):
        space.add_member("alice", "Again")


def test_resource_validation(space):
    for kwargs in ({"id": "Room", "name": "x"}, {"id": "r", "name": " "}, {"id": "r", "name": "x", "capacity": 0},
                   {"id": "r", "name": "x", "kind": "desk", "capacity": 2}, {"id": "r", "name": "x", "buffer_minutes": 10},
                   {"id": "r", "name": "x", "hours": "mon 10:00-10:00"}):
        with pytest.raises(ValueError):
            space.add_resource(**kwargs)


def test_insufficient_credits_basic(space):
    space.add_resource("big", "Big", capacity=20, credits_per_hour=20)
    space.book("big", "alice", dt(20, 9), dt(20, 11))                 # 40
    with pytest.raises(InsufficientCredits):
        space.book("room-a", "alice", dt(21, 9), dt(21, 10))
    space.book("big", "bob", dt(21, 9), dt(21, 17))                   # pro: 초과 허용


def test_advance_limit(space):
    with pytest.raises(PolicyError):
        space.book("room-a", "alice", datetime(2026, 11, 19, 10), datetime(2026, 11, 19, 11))
    space.book("room-a", "bob", datetime(2026, 11, 19, 10), datetime(2026, 11, 19, 11))


def test_bookings_query(space):
    a = space.book("room-a", "alice", dt(21, 10), dt(21, 11))
    b = space.book("room-b", "bob", dt(20, 10), dt(20, 11))
    c = space.book("room-a", "bob", dt(20, 14), dt(20, 15))
    assert [x.id for x in space.bookings()] == [b.id, c.id, a.id]
    assert [x.id for x in space.bookings(resource_id="room-a")] == [c.id, a.id]
    assert [x.id for x in space.bookings(member_id="bob")] == [b.id, c.id]
    assert [x.id for x in space.bookings(start=dt(20, 14, 30), end=dt(21, 10, 30))] == [c.id, a.id]
    space.cancel(a.id)
    assert a.id not in [x.id for x in space.bookings()]
    assert a.id in [x.id for x in space.bookings(include_cancelled=True)]


def test_cancel_twice(space):
    b = space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    space.cancel(b.id)
    with pytest.raises(BookingError):
        space.cancel(b.id)


def test_move_basic(space):
    b = space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    moved = space.move(b.id, dt(20, 14), dt(20, 15))
    assert (moved.start, moved.end) == (dt(20, 14), dt(20, 15))
    other = space.book("room-a", "bob", dt(20, 10), dt(20, 11))
    with pytest.raises(Conflict):
        space.move(other.id, dt(20, 14, 30), dt(20, 15, 30))


def test_free_slots_simple(space):
    space.book("room-a", "alice", dt(20, 9), dt(20, 19))
    slots = space.free_slots("room-a", datetime(2026, 10, 20).date(), 60)
    assert slots == [dt(20, 8), dt(20, 19)]
