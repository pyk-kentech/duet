from datetime import date, datetime, timedelta

import pytest

from booking import AlreadyExists, BookingError, Conflict, OutsideHours, UnknownEntry, UnknownSeries


def dt(day, hh, mm=0, month=10):
    return datetime(2026, month, day, hh, mm)


def test_series_count(space):
    s = space.book_series("room-a", "bob", dt(20, 10), dt(20, 11), count=3)
    starts = [space.booking(i).start for i in s.booking_ids]
    assert starts == [dt(20, 10), dt(27, 10), dt(3, 10, month=11)]
    assert all(space.booking(i).series_id == s.id for i in s.booking_ids)
    assert space.series(s.id) is s and space.all_series() == [s]


def test_series_until_biweekly(space):
    s = space.book_series("room-a", "bob", dt(20, 10), dt(20, 11), freq="biweekly", until=date(2026, 11, 17))
    assert [space.booking(i).start.date() for i in s.booking_ids] == [date(2026, 10, 20), date(2026, 11, 3),
                                                                       date(2026, 11, 17)]


def test_series_needs_exactly_one_limit(space):
    with pytest.raises(ValueError):
        space.book_series("room-a", "bob", dt(20, 10), dt(20, 11))
    with pytest.raises(ValueError):
        space.book_series("room-a", "bob", dt(20, 10), dt(20, 11), count=2, until=date(2026, 11, 3))
    with pytest.raises(ValueError):
        space.book_series("room-a", "bob", dt(20, 10), dt(20, 11), count=2, freq="daily")


def test_series_all_or_nothing(space):
    space.book("room-a", "alice", dt(27, 10, 30), dt(27, 11))
    with pytest.raises(Conflict):
        space.book_series("room-a", "bob", dt(20, 10), dt(20, 11), count=3)
    assert len(space.bookings()) == 1


def test_series_skip_conflicts(space):
    space.book("room-a", "alice", dt(27, 10, 30), dt(27, 11))
    s = space.book_series("room-a", "bob", dt(20, 10), dt(20, 11), count=3, skip_conflicts=True)
    assert len(s.booking_ids) == 2 and s.exceptions == {date(2026, 10, 27)}


def test_series_outside_hours(space):
    with pytest.raises(OutsideHours):
        space.book_series("room-a", "bob", dt(24, 10), dt(24, 11), count=2)


def test_cancel_series(space, clock):
    s = space.book_series("room-a", "bob", dt(20, 10), dt(20, 11), count=3)
    results = space.cancel_series(s.id)
    assert [r.booking_id for r in results] == s.booking_ids
    assert all(not space.booking(i).active for i in s.booking_ids)
    with pytest.raises(UnknownSeries):
        space.cancel_series(99)


def test_skip_occurrence(space):
    s = space.book_series("room-a", "bob", dt(20, 10), dt(20, 11), count=3)
    r = space.skip_occurrence(s.id, date(2026, 10, 27))
    assert r.booking_id == s.booking_ids[1] and date(2026, 10, 27) in s.exceptions
    with pytest.raises(BookingError):
        space.skip_occurrence(s.id, date(2026, 10, 28))


def test_waitlist_join_and_promote(space):
    b = space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    e = space.join_waitlist("room-a", "bob", dt(20, 10), dt(20, 11))
    assert space.waitlist() == [e] and space.waitlist("room-a") == [e]
    space.cancel(b.id)
    assert space.waitlist() == []
    [nb] = space.bookings()
    assert (nb.member_id, nb.start, nb.note) == ("bob", dt(20, 10), "waitlist")


def test_waitlist_requires_taken_slot(space):
    with pytest.raises(BookingError):
        space.join_waitlist("room-a", "bob", dt(20, 10), dt(20, 11))


def test_waitlist_duplicate_and_leave(space):
    space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    e = space.join_waitlist("room-a", "bob", dt(20, 10), dt(20, 11))
    with pytest.raises(AlreadyExists):
        space.join_waitlist("room-a", "bob", dt(20, 10), dt(20, 11))
    space.leave_waitlist(e.id)
    with pytest.raises(UnknownEntry):
        space.leave_waitlist(e.id)


def test_waitlist_fifo(space):
    b = space.book("room-a", "alice", dt(20, 10), dt(20, 11))
    space.join_waitlist("room-a", "bob", dt(20, 10), dt(20, 11))
    space.join_waitlist("room-a", "carol", dt(20, 10), dt(20, 11))
    space.cancel(b.id)
    assert [x.member_id for x in space.bookings()] == ["bob"]
    assert [x.member_id for x in space.waitlist()] == ["carol"]
