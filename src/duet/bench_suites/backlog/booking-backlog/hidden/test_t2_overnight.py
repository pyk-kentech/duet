"""#2 자정을 넘는 영업시간."""

import os
import subprocess
import sys
from datetime import date, datetime, time

import pytest

from booking import OutsideHours, Space, format_hours, parse_hours
from booking.reports import utilization

NOW = datetime(2026, 10, 19, 9, 0)      # 월요일. 금요일 = 10-23, 토요일 = 10-24


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
    s.add_resource("lab", "Night Lab", capacity=20, credits_per_hour=4, hours="mon-thu 09:00-18:00; fri 18:00-02:00")
    s.add_resource("late", "Late", capacity=4, credits_per_hour=4, hours="fri 22:00-02:00")
    s.add_member("alice", "Alice", plan="pro")
    s.add_member("bob", "Bob", plan="pro")
    return s


# ---------------------------------------------------------------- 문자열
def test_parse_and_format_overnight():
    assert parse_hours("fri 18:00-02:00") == {4: (time(18), time(2))}
    spec = "mon-thu 09:00-18:00; fri 18:00-02:00"
    assert format_hours(parse_hours(spec)) == spec
    assert format_hours(parse_hours("mon-fri 22:00-02:00")) == "mon-fri 22:00-02:00"


def test_midnight_close_string():
    h = parse_hours("sat 20:00-00:00")
    assert h == {5: (time(20), time(0))} and format_hours(h) == "sat 20:00-00:00"


@pytest.mark.parametrize("spec", ["fri 18:00-02:00; sat 01:00-05:00", "sun 22:00-03:00; mon 02:00-09:00"],
                         ids=["next-day", "week-wrap"])
def test_overnight_overlapping_next_day_rejected(spec):
    with pytest.raises(ValueError):
        parse_hours(spec)


# ---------------------------------------------------------------- 단건 예약
def test_book_across_midnight(space):
    b = space.book("lab", "alice", dt(23, 23), dt(24, 1))
    assert (b.start, b.end, b.charged) == (dt(23, 23), dt(24, 1), 4)    # 금 23시 시작: 비수기 절반


def test_book_after_midnight_in_previous_days_range(space):
    b = space.book("lab", "bob", dt(24, 0, 30), dt(24, 2))
    assert (b.start, b.end) == (dt(24, 0, 30), dt(24, 2))


def test_book_past_overnight_close_rejected(space):
    with pytest.raises(OutsideHours):
        space.book("lab", "alice", dt(24, 1, 30), dt(24, 2, 30))
    with pytest.raises(OutsideHours):
        space.book("lab", "alice", dt(25, 0, 30), dt(25, 1))            # 일요일 새벽: 토요일 구간 없음


def test_booking_cannot_span_two_ranges(space):
    space.add_resource("lab2", "Lab 2", capacity=4, credits_per_hour=4, hours="fri 18:00-02:00; sat 02:00-06:00")
    with pytest.raises(OutsideHours):
        space.book("lab2", "alice", dt(24, 1), dt(24, 3))
    space.book("lab2", "alice", dt(24, 1), dt(24, 2))
    space.book("lab2", "alice", dt(24, 2), dt(24, 3))


# ---------------------------------------------------------------- 다른 경로
def test_series_overnight(space):
    s = space.book_series("lab", "alice", dt(23, 23), dt(24, 1), count=3)
    assert [space.booking(i).start for i in s.booking_ids] == [dt(23, 23), dt(30, 23), dt(6, 23, month=11)]
    assert space.balance("alice", "2026-10") == 112 and space.balance("alice", "2026-11") == 116


def test_move_into_overnight(space):
    b = space.book("lab", "alice", dt(23, 19), dt(23, 20))
    space.move(b.id, dt(23, 23, 30), dt(24, 0, 30))
    assert (b.start, b.end) == (dt(23, 23, 30), dt(24, 0, 30))


def test_waitlist_after_midnight(space):
    b = space.book("lab", "alice", dt(23, 23), dt(24, 1))
    e = space.join_waitlist("lab", "bob", dt(24, 0), dt(24, 1))
    space.cancel(b.id)
    assert [x.member_id for x in space.bookings(resource_id="lab")] == ["bob"]
    assert e.id not in [x.id for x in space.waitlist()]


# ---------------------------------------------------------------- 빈 시각
def test_free_slots_continue_past_midnight(space):
    space.add_resource("short", "Short", capacity=4, credits_per_hour=4, hours="fri 22:00-01:00")
    assert space.free_slots("short", date(2026, 10, 23), 60) == [
        dt(23, 22), dt(23, 22, 15), dt(23, 22, 30), dt(23, 22, 45), dt(23, 23), dt(23, 23, 15), dt(23, 23, 30),
        dt(23, 23, 45), dt(24, 0)]


def test_free_slots_next_day_excludes_previous_range(space):
    assert space.free_slots("late", date(2026, 10, 24), 60) == []


# ---------------------------------------------------------------- 가동률
def test_utilization_counts_previous_days_overnight_part(space):
    space.book("late", "alice", dt(23, 23), dt(24, 1))
    [sat] = utilization(space, dt(24, 0), dt(25, 0), resource_id="late")
    assert (sat.open_minutes, sat.booked_minutes, sat.percent) == (120, 60, 50.0)


def test_utilization_window_starting_inside_overnight_part(space):
    space.book("late", "alice", dt(23, 23), dt(24, 1))
    [row] = utilization(space, dt(24, 0, 30), dt(24, 3), resource_id="late")
    assert (row.open_minutes, row.booked_minutes, row.percent) == (90, 30, 33.3)


def test_utilization_overnight_week_and_friday(space):
    space.book("late", "alice", dt(23, 23), dt(24, 1))
    [week] = utilization(space, dt(19, 0), dt(26, 0), resource_id="late")
    [fri] = utilization(space, dt(23, 0), dt(24, 0), resource_id="late")
    assert (week.open_minutes, week.booked_minutes, fri.open_minutes, fri.booked_minutes) == (240, 120, 120, 60)


# ---------------------------------------------------------------- CLI
def test_cli_overnight(tmp_path):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "booking", "--db", str(tmp_path / "b.json"), "--now",
                               "2026-10-19T09:00", *args], capture_output=True, text=True, encoding="utf-8", env=env)

    r = cli("resource-add", "lab", "Lab", "--capacity", "8", "--hours", "fri 18:00-02:00")
    assert r.returncode == 0, r.stderr
    assert cli("resources").stdout.splitlines() == ["lab\troom\t8\t4\t0\tfri 18:00-02:00"]
    assert cli("member-add", "alice", "Alice").returncode == 0
    r = cli("book", "lab", "alice", "2026-10-23T23:00", "2026-10-24T01:00")
    assert r.stdout.strip() == "1\t2026-10-23T23:00\t2026-10-24T01:00\t4"
    assert cli("free", "lab", "2026-10-23", "60").stdout.splitlines()[-1] == "2026-10-24T01:00"
