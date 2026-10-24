"""반복 일정: daily, monthly (틈·겹침 정책, 없는 날짜, 셈 규칙, 인자 검사)."""

from datetime import date, datetime, time, timezone

import pytest

from tzrule import TZ

D = datetime
NY = TZ("EST5EDT,M3.2.0,M11.1.0")
LON = TZ("GMT0BST,M3.5.0/1,M10.5.0")


# ---------------------------------------------------------------- daily
def test_daily_gap_shift_default():
    assert NY.daily(time(2, 30), date(2026, 3, 7), 3) == [
        D(2026, 3, 7, 7, 30), D(2026, 3, 8, 7, 30), D(2026, 3, 9, 6, 30)]


def test_daily_gap_skip_shortens_list():
    assert NY.daily(time(2, 30), date(2026, 3, 7), 3, gap="skip") == [D(2026, 3, 7, 7, 30), D(2026, 3, 9, 6, 30)]


@pytest.mark.parametrize("ambiguous,expected", [
    ("first", [D(2026, 10, 31, 5, 30), D(2026, 11, 1, 5, 30), D(2026, 11, 2, 6, 30)]),
    ("last", [D(2026, 10, 31, 5, 30), D(2026, 11, 1, 6, 30), D(2026, 11, 2, 6, 30)]),
    ("both", [D(2026, 10, 31, 5, 30), D(2026, 11, 1, 5, 30), D(2026, 11, 1, 6, 30), D(2026, 11, 2, 6, 30)]),
])
def test_daily_ambiguous_policies(ambiguous, expected):
    assert NY.daily(time(1, 30), date(2026, 10, 31), 3, ambiguous=ambiguous) == expected


def test_daily_zero_days_is_empty():
    assert NY.daily(time(9), date(2026, 1, 1), 0) == []


def test_daily_ordinary_days_and_month_end():
    got = NY.daily(time(23, 59, 59), date(2026, 2, 27), 3)
    assert got == [D(2026, 2, 28, 4, 59, 59), D(2026, 3, 1, 4, 59, 59), D(2026, 3, 2, 4, 59, 59)]


def test_daily_at_fold_attribute_ignored():
    assert NY.daily(time(1, 30, fold=1), date(2026, 11, 1), 1) == [D(2026, 11, 1, 5, 30)]


def test_daily_southern_gap():
    syd = TZ("AEST-10AEDT,M10.1.0,M4.1.0/3")
    assert syd.daily(time(2, 15), date(2026, 10, 3), 3) == [
        D(2026, 10, 2, 16, 15), D(2026, 10, 3, 16, 15), D(2026, 10, 4, 15, 15)]


def test_daily_gap_on_previous_calendar_day():
    nuuk = TZ("<-02>2<-01>,M3.5.0/-1,M10.5.0/0")
    assert nuuk.daily(time(23, 30), date(2026, 3, 27), 3) == [
        D(2026, 3, 28, 1, 30), D(2026, 3, 29, 1, 30), D(2026, 3, 30, 0, 30)]


def test_daily_across_new_year_transitions():
    tz = TZ("EST5EDT4,0/0,J365/24")
    assert tz.daily(time(0, 30), date(2025, 12, 31), 2) == [D(2025, 12, 31, 4, 30), D(2026, 1, 1, 5, 30)]
    assert tz.daily(time(23, 30), date(2025, 12, 30), 2, ambiguous="both") == [
        D(2025, 12, 31, 3, 30), D(2026, 1, 1, 3, 30), D(2026, 1, 1, 4, 30)]
    assert tz.daily(time(0, 30), date(2025, 12, 31), 2, gap="skip") == [D(2025, 12, 31, 4, 30)]


def test_daily_new_year_eve_gap_from_next_years_rule():
    eve = TZ("XXX-2YYY,J1/-1,J300")
    assert eve.daily(time(23, 30), date(2026, 12, 30), 3) == [
        D(2026, 12, 30, 21, 30), D(2026, 12, 31, 21, 30), D(2027, 1, 1, 20, 30)]
    assert eve.daily(time(23, 30), date(2026, 12, 30), 3, gap="skip") == [
        D(2026, 12, 30, 21, 30), D(2027, 1, 1, 20, 30)]


@pytest.mark.parametrize("kwargs", [
    {"gap": "forward"},
    {"gap": "SHIFT"},
    {"ambiguous": "earliest"},
    {"ambiguous": None},
])
def test_daily_bad_policy_rejected_even_with_zero_days(kwargs):
    with pytest.raises(ValueError):
        NY.daily(time(9), date(2026, 1, 1), 0, **kwargs)


@pytest.mark.parametrize("at,start,days", [
    (time(9, tzinfo=timezone.utc), date(2026, 1, 1), 1),
    (time(9), datetime(2026, 1, 1), 1),
    (time(9), date(2026, 1, 1), -1),
])
def test_daily_bad_arguments(at, start, days):
    with pytest.raises(ValueError):
        NY.daily(at, start, days)


# ---------------------------------------------------------------- monthly
LON_LAST_SUNDAYS_0130 = [
    D(2026, 1, 25, 1, 30), D(2026, 2, 22, 1, 30), D(2026, 3, 29, 1, 30), D(2026, 4, 26, 0, 30),
    D(2026, 5, 31, 0, 30), D(2026, 6, 28, 0, 30), D(2026, 7, 26, 0, 30), D(2026, 8, 30, 0, 30),
    D(2026, 9, 27, 0, 30), D(2026, 10, 25, 0, 30), D(2026, 11, 29, 1, 30), D(2026, 12, 27, 1, 30),
]


def test_monthly_last_sunday_full_year():
    # 3월 29일 01:30 은 틈(shift), 10월 25일 01:30 은 겹침(first)
    assert LON.monthly(time(1, 30), date(2026, 1, 1), 12, week=5, weekday=0) == LON_LAST_SUNDAYS_0130


def test_monthly_skip_does_not_count():
    assert LON.monthly(time(1, 30), date(2026, 2, 1), 3, week=5, weekday=0, gap="skip") == [
        D(2026, 2, 22, 1, 30), D(2026, 4, 26, 0, 30), D(2026, 5, 31, 0, 30)]


def test_monthly_both_counts_once():
    assert LON.monthly(time(1, 30), date(2026, 10, 1), 2, week=5, weekday=0, ambiguous="both") == [
        D(2026, 10, 25, 0, 30), D(2026, 10, 25, 1, 30), D(2026, 11, 29, 1, 30)]


def test_monthly_day_skip_in_gap_does_not_count():
    assert NY.monthly(time(2, 30), date(2026, 2, 1), 3, day=8, gap="skip") == [
        D(2026, 2, 8, 7, 30), D(2026, 4, 8, 6, 30), D(2026, 5, 8, 6, 30)]
    assert NY.monthly(time(2, 30), date(2026, 2, 1), 3, day=8) == [
        D(2026, 2, 8, 7, 30), D(2026, 3, 8, 7, 30), D(2026, 4, 8, 6, 30)]


def test_monthly_first_sunday_both_counts_once():
    assert NY.monthly(time(1, 30), date(2026, 10, 1), 3, week=1, weekday=0, ambiguous="both") == [
        D(2026, 10, 4, 5, 30), D(2026, 11, 1, 5, 30), D(2026, 11, 1, 6, 30), D(2026, 12, 6, 6, 30)]


def test_monthly_last_ambiguous():
    assert LON.monthly(time(1, 30), date(2026, 10, 1), 1, week=5, weekday=0, ambiguous="last") == [
        D(2026, 10, 25, 1, 30)]


def test_monthly_day_31_skips_short_months():
    assert NY.monthly(time(12), date(2026, 1, 15), 4, day=31) == [
        D(2026, 1, 31, 17), D(2026, 3, 31, 16), D(2026, 5, 31, 16), D(2026, 7, 31, 16)]


def test_monthly_day_29_february_only_in_leap_years():
    assert NY.monthly(time(12), date(2027, 1, 1), 3, day=29) == [
        D(2027, 1, 29, 17), D(2027, 3, 29, 16), D(2027, 4, 29, 16)]
    assert NY.monthly(time(12), date(2028, 2, 1), 1, day=29) == [D(2028, 2, 29, 17)]


def test_monthly_start_date_inclusive_and_earlier_days_excluded():
    assert NY.monthly(time(9), date(2026, 3, 15), 2, day=10) == [D(2026, 4, 10, 13), D(2026, 5, 10, 13)]
    assert NY.monthly(time(9), date(2026, 3, 10), 1, day=10) == [D(2026, 3, 10, 13)]
    assert NY.monthly(time(9), date(2026, 3, 9), 1, week=2, weekday=0) == [D(2026, 4, 12, 13)]


def test_monthly_weekday_zero_is_sunday_one_is_monday():
    assert NY.monthly(time(12), date(2026, 1, 1), 3, week=1, weekday=1) == [
        D(2026, 1, 5, 17), D(2026, 2, 2, 17), D(2026, 3, 2, 17)]
    assert NY.monthly(time(12), date(2026, 1, 1), 2, week=1, weekday=0) == [D(2026, 1, 4, 17), D(2026, 2, 1, 17)]


def test_monthly_week_five_vs_four():
    assert NY.monthly(time(12), date(2026, 5, 1), 2, week=5, weekday=0) == [D(2026, 5, 31, 16), D(2026, 6, 28, 16)]
    assert NY.monthly(time(12), date(2026, 5, 1), 2, week=4, weekday=0) == [D(2026, 5, 24, 16), D(2026, 6, 28, 16)]


def test_monthly_crosses_year():
    assert NY.monthly(time(0), date(2026, 11, 20), 3, day=15) == [
        D(2026, 12, 15, 5), D(2027, 1, 15, 5), D(2027, 2, 15, 5)]


def test_monthly_zero_count_is_empty():
    assert NY.monthly(time(9), date(2026, 1, 1), 0, day=1) == []


@pytest.mark.parametrize("kwargs", [
    {},
    {"day": 1, "week": 1, "weekday": 0},
    {"day": 1, "weekday": 0},
    {"week": 1},
    {"weekday": 0},
    {"day": 0},
    {"day": 32},
    {"week": 0, "weekday": 0},
    {"week": 6, "weekday": 0},
    {"week": 1, "weekday": 7},
    {"week": 1, "weekday": -1},
    {"day": 1, "gap": "later"},
    {"day": 1, "ambiguous": "second"},
])
def test_monthly_bad_arguments(kwargs):
    with pytest.raises(ValueError):
        NY.monthly(time(9), date(2026, 1, 1), 1, **kwargs)


def test_monthly_negative_count_and_datetime_start():
    with pytest.raises(ValueError):
        NY.monthly(time(9), date(2026, 1, 1), -1, day=1)
    with pytest.raises(ValueError):
        NY.monthly(time(9), datetime(2026, 1, 1), 1, day=1)
