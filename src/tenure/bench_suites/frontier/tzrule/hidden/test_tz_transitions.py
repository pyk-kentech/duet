"""규칙 날짜(Jn, n, Mm.w.d), 전이 시각, 시각선 모델(해 넘김, 1년 내내 DST), next_transition."""

from datetime import datetime, timedelta, timezone

import pytest

from tzrule import TZ


def H(h=0, m=0, s=0):
    return timedelta(hours=h, minutes=m, seconds=s)


def D(*a):
    return datetime(*a)


def T(tz, year):
    return [tuple(t) for t in TZ(tz).transitions(year)]


REAL = [
    ("EST5EDT,M3.2.0,M11.1.0", 2026,
     [(D(2026, 3, 8, 7), H(-5), H(-4)), (D(2026, 11, 1, 6), H(-4), H(-5))]),
    ("EST5EDT,M3.2.0,M11.1.0", 2024,
     [(D(2024, 3, 10, 7), H(-5), H(-4)), (D(2024, 11, 3, 6), H(-4), H(-5))]),
    ("GMT0BST,M3.5.0/1,M10.5.0", 2026,
     [(D(2026, 3, 29, 1), H(0), H(1)), (D(2026, 10, 25, 1), H(1), H(0))]),
    ("AEST-10AEDT,M10.1.0,M4.1.0/3", 2026,
     [(D(2026, 4, 4, 16), H(11), H(10)), (D(2026, 10, 3, 16), H(10), H(11))]),
    ("IST-1GMT0,M10.5.0,M3.5.0/1", 2026,
     [(D(2026, 3, 29, 1), H(0), H(1)), (D(2026, 10, 25, 1), H(1), H(0))]),
    ("<-02>2<-01>,M3.5.0/-1,M10.5.0/0", 2026,
     [(D(2026, 3, 29, 1), H(-2), H(-1)), (D(2026, 10, 25, 1), H(-1), H(-2))]),
    ("<+1245>-12:45<+1345>,M9.5.0/2:45,M4.1.0/3:45", 2026,
     [(D(2026, 4, 4, 14), H(13, 45), H(12, 45)), (D(2026, 9, 26, 14), H(12, 45), H(13, 45))]),
    ("<-04>4<-03>,M9.1.6/24,M4.1.6/24", 2026,
     [(D(2026, 4, 5, 3), H(-3), H(-4)), (D(2026, 9, 6, 4), H(-4), H(-3))]),
    ("EET-2EEST,M3.4.4/50,M10.4.4/50", 2026,
     [(D(2026, 3, 28, 0), H(2), H(3)), (D(2026, 10, 23, 23), H(3), H(2))]),
    ("EET-2EEST,M4.5.5/0,M10.5.4/24", 2026,
     [(D(2026, 4, 23, 22), H(2), H(3)), (D(2026, 10, 29, 21), H(3), H(2))]),
    ("<+1030>-10:30<+11>-11,M10.1.0,M4.1.0", 2026,
     [(D(2026, 4, 4, 15), H(11), H(10, 30)), (D(2026, 10, 3, 15, 30), H(10, 30), H(11))]),
    ("<+00>0<+02>-2,M3.5.0/1,M10.5.0/3", 2026,
     [(D(2026, 3, 29, 1), H(0), H(2)), (D(2026, 10, 25, 1), H(2), H(0))]),
    ("<+0330>-3:30<+0430>,J79/24,J263/24", 2026,
     [(D(2026, 3, 20, 20, 30), H(3, 30), H(4, 30)), (D(2026, 9, 20, 19, 30), H(4, 30), H(3, 30))]),
    ("<+0330>-3:30<+0430>,J79/24,J263/24", 2020,
     [(D(2020, 3, 20, 20, 30), H(3, 30), H(4, 30)), (D(2020, 9, 20, 19, 30), H(4, 30), H(3, 30))]),
]


@pytest.mark.parametrize("spec,year,expected", REAL)
def test_real_world_rules(spec, year, expected):
    assert T(spec, year) == expected


def test_transitions_are_list_of_naive_utc_triples():
    trs = TZ("EST5EDT,M3.2.0,M11.1.0").transitions(2026)
    assert isinstance(trs, list) and len(trs) == 2
    for t in trs:
        assert len(t) == 3 and isinstance(t[0], datetime) and t[0].tzinfo is None


def test_southern_hemisphere_order_is_chronological():
    trs = T("AEST-10AEDT,M10.1.0,M4.1.0/3", 2027)
    assert [t[0] for t in trs] == [D(2027, 4, 3, 16), D(2027, 10, 2, 16)]
    assert trs[0][2] < trs[0][1]          # 4월: DST 끝


@pytest.mark.parametrize("spec", ["EST5EDT", "EST5EDT4"])
def test_default_rules_are_us_rules(spec):
    assert T(spec, 2026) == T("EST5EDT,M3.2.0,M11.1.0", 2026)
    assert T(spec, 2027) == [(D(2027, 3, 14, 7), H(-5), H(-4)), (D(2027, 11, 7, 6), H(-4), H(-5))]


# ---------------------------------------------------------------- Jn / n
def test_julian_j60_is_march_first_in_leap_and_common_years():
    assert T("XXX3YYY,J60/0,J300/0", 2024) == [(D(2024, 3, 1, 3), H(-3), H(-2)), (D(2024, 10, 27, 2), H(-2), H(-3))]
    assert T("XXX3YYY,J60/0,J300/0", 2025) == [(D(2025, 3, 1, 3), H(-3), H(-2)), (D(2025, 10, 27, 2), H(-2), H(-3))]


def test_julian_j59_is_feb_28_even_in_leap_year():
    assert T("XXX3YYY,J59/0,J300/0", 2024)[0][0] == D(2024, 2, 28, 3)


def test_julian_j59_end_rule_in_leap_year():
    assert T("XXX3YYY,J1/0,J59/0", 2028) == [(D(2028, 1, 1, 3), H(-3), H(-2)), (D(2028, 2, 28, 2), H(-2), H(-3))]


def test_julian_leading_zeros_allowed():
    assert T("XXX3YYY,J060/0,J300/0", 2024) == T("XXX3YYY,J60/0,J300/0", 2024)


def test_zero_based_n_counts_feb_29():
    assert T("XXX3YYY,59/0,300/0", 2024) == [(D(2024, 2, 29, 3), H(-3), H(-2)), (D(2024, 10, 27, 2), H(-2), H(-3))]
    assert T("XXX3YYY,59/0,300/0", 2025) == [(D(2025, 3, 1, 3), H(-3), H(-2)), (D(2025, 10, 28, 2), H(-2), H(-3))]


def test_zero_based_n_zero_is_january_first():
    assert T("XXX3YYY,0/12,J200/0", 2026)[0] == (D(2026, 1, 1, 15), H(-3), H(-2))


def test_n_365_in_common_year_is_next_january_first():
    # 끝 365: 평년이면 다음 해 1월 1일, 윤년이면 12월 31일
    tz = "XXX3YYY,0,365"
    assert T(tz, 2024) == [(D(2024, 1, 1, 4), H(-2), H(-3)), (D(2024, 1, 1, 5), H(-3), H(-2)),
                           (D(2024, 12, 31, 4), H(-2), H(-3))]
    assert T(tz, 2025) == [(D(2025, 1, 1, 5), H(-3), H(-2))]
    assert T(tz, 2026) == [(D(2026, 1, 1, 4), H(-2), H(-3)), (D(2026, 1, 1, 5), H(-3), H(-2))]


# ---------------------------------------------------------------- Mm.w.d
def test_week_five_means_last_and_week_four_is_fourth():
    # 2026년 5월은 일요일이 5번(3,10,17,24,31), 6월은 4번(7,14,21,28)
    assert T("XXX3YYY,M5.4.0/0,M6.5.0/0", 2026) == [(D(2026, 5, 24, 3), H(-3), H(-2)), (D(2026, 6, 28, 2), H(-2), H(-3))]
    assert T("XXX3YYY,M5.5.0/0,M8.1.6/0", 2026) == [(D(2026, 5, 31, 3), H(-3), H(-2)), (D(2026, 8, 1, 2), H(-2), H(-3))]


def test_weekday_zero_is_sunday_one_is_monday():
    assert T("XXX3YYY,M3.1.1/0,M10.1.1/0", 2026) == [(D(2026, 3, 2, 3), H(-3), H(-2)), (D(2026, 10, 5, 2), H(-2), H(-3))]
    assert T("XXX3YYY,M2.1.0/0,M10.2.6/0", 2026) == [(D(2026, 2, 1, 3), H(-3), H(-2)), (D(2026, 10, 10, 2), H(-2), H(-3))]


def test_month_with_leading_zero():
    assert T("XXX3YYY,M03.2.0,M11.1.0", 2026) == T("XXX3YYY,M3.2.0,M11.1.0", 2026)


def test_feb_last_sunday_leap_year():
    # 2032년 2월 29일은 일요일
    assert T("XXX3YYY,M2.5.0/0,M10.5.0/0", 2032)[0][0] == D(2032, 2, 29, 3)
    assert T("XXX3YYY,M2.5.0/0,M10.5.0/0", 2031)[0][0] == D(2031, 2, 23, 3)


# ---------------------------------------------------------------- 전이 시각
def test_negative_and_over_24_transition_times():
    assert T("XXX3YYY,M3.2.0/-1,M11.1.0/25", 2026) == [(D(2026, 3, 8, 2), H(-3), H(-2)), (D(2026, 11, 2, 3), H(-2), H(-3))]


def test_transition_time_167_hours_either_way():
    assert T("XXX3YYY,M3.2.0/167,M11.1.0/-167", 2026) == [(D(2026, 3, 15, 2), H(-3), H(-2)), (D(2026, 10, 25, 3), H(-2), H(-3))]


def test_transition_time_with_minutes_and_seconds():
    assert T("XXX3YYY,M3.2.0/2:45:30,M11.1.0/1:15:15", 2026) == [
        (D(2026, 3, 8, 5, 45, 30), H(-3), H(-2)), (D(2026, 11, 1, 3, 15, 15), H(-2), H(-3))]


def test_negative_transition_time_sign_applies_to_minutes():
    assert T("XXX3YYY,M3.2.0/-1:30,M11.1.0/25:30:15", 2026) == [
        (D(2026, 3, 8, 1, 30), H(-3), H(-2)), (D(2026, 11, 2, 3, 30, 15), H(-2), H(-3))]
    assert T("<+0030>-0:30<+0130>,M3.5.0/-0:30,M10.5.0/-0:30", 2026) == [
        (D(2026, 3, 28, 23, 0), H(0, 30), H(1, 30)), (D(2026, 10, 24, 22, 0), H(1, 30), H(0, 30))]


# ---------------------------------------------------------------- 시각선 모델
def test_start_rule_from_next_year_falls_into_this_utc_year():
    # S(Y) = Y년 1월 1일 05:00 (+10) = 전년도 12월 31일 19:00 UTC
    tz = "XXX-10YYY,J1/5,J200"
    assert T(tz, 2026) == [(D(2026, 7, 18, 15), H(11), H(10)), (D(2026, 12, 31, 19), H(10), H(11))]
    assert T(tz, 2027)[0] == (D(2027, 7, 18, 15), H(11), H(10))
    assert len(T(tz, 2027)) == 2


def test_end_rule_spills_into_next_utc_year():
    # E(Y) = 12월 31일 23:00 (-2) = 다음 해 1월 1일 01:00 UTC
    tz = "XXX3YYY,J60,J365/23"
    assert T(tz, 2026) == [(D(2026, 1, 1, 1), H(-2), H(-3)), (D(2026, 3, 1, 5), H(-3), H(-2))]
    assert T(tz, 2025) == [(D(2025, 1, 1, 1), H(-2), H(-3)), (D(2025, 3, 1, 5), H(-3), H(-2))]


def test_negative_time_on_january_first_falls_into_previous_utc_year():
    # S(Y) = 전년도 12월 31일 23:00 (+2) = 21:00 UTC
    assert T("XXX-2YYY,J1/-1,J300", 2026) == [(D(2026, 10, 26, 23), H(3), H(2)), (D(2026, 12, 31, 21), H(2), H(3))]


@pytest.mark.parametrize("year", [2024, 2025, 2026])
def test_dst_all_year_has_no_transitions(year):
    assert TZ("EST5EDT4,0/0,J365/25").transitions(year) == []


def test_overlapping_periods_merge_into_all_year():
    assert TZ("EST5EDT4,0/0,J365/26").transitions(2026) == []


def test_one_hour_of_standard_time_at_new_year():
    # E(Y) = 다음 해 1월 1일 04:00 UTC, S(Y+1) = 1월 1일 05:00 UTC
    tz = "EST5EDT4,0/0,J365/24"
    assert T(tz, 2026) == [(D(2026, 1, 1, 4), H(-4), H(-5)), (D(2026, 1, 1, 5), H(-5), H(-4))]
    assert T(tz, 2025) == [(D(2025, 1, 1, 4), H(-4), H(-5)), (D(2025, 1, 1, 5), H(-5), H(-4))]


@pytest.mark.parametrize("spec", ["<-03>3", "UTC0", "IST-5:30"])
def test_no_dst_has_no_transitions(spec):
    assert TZ(spec).transitions(2026) == []


@pytest.mark.parametrize("year", [0, -1, 10000])
def test_year_out_of_range(year):
    with pytest.raises(ValueError):
        TZ("EST5EDT").transitions(year)


# ---------------------------------------------------------------- next_transition
NY = "EST5EDT,M3.2.0,M11.1.0"


def test_next_transition_basic_and_strictly_after():
    tz = TZ(NY)
    assert tuple(tz.next_transition(D(2026, 3, 8, 6, 59, 59))) == (D(2026, 3, 8, 7), H(-5), H(-4))
    assert tuple(tz.next_transition(D(2026, 3, 8, 7))) == (D(2026, 11, 1, 6), H(-4), H(-5))


def test_next_transition_crosses_into_next_year():
    assert tuple(TZ(NY).next_transition(D(2026, 11, 1, 6))) == (D(2027, 3, 14, 7), H(-5), H(-4))
    assert tuple(TZ("AEST-10AEDT,M10.1.0,M4.1.0/3").next_transition(D(2026, 12, 31))) == (
        D(2027, 4, 3, 16), H(11), H(10))


def test_next_transition_accepts_aware_datetime():
    at = datetime(2026, 3, 8, 2, 0, tzinfo=timezone(H(-5)))      # = 07:00 UTC
    assert tuple(TZ(NY).next_transition(at)) == (D(2026, 11, 1, 6), H(-4), H(-5))


def test_next_transition_cross_year_rule():
    tz = TZ("XXX-10YYY,J1/5,J200")
    assert tuple(tz.next_transition(D(2026, 12, 31, 18))) == (D(2026, 12, 31, 19), H(10), H(11))
    assert tuple(tz.next_transition(D(2026, 12, 31, 19))) == (D(2027, 7, 18, 15), H(11), H(10))


def test_next_transition_spilled_end_rule():
    tz = TZ("XXX3YYY,J60,J365/23")
    assert tuple(tz.next_transition(D(2025, 12, 31, 12))) == (D(2026, 1, 1, 1), H(-2), H(-3))
    assert tuple(tz.next_transition(D(2026, 1, 1, 1))) == (D(2026, 3, 1, 5), H(-3), H(-2))


@pytest.mark.parametrize("spec", ["<-03>3", "EST5EDT4,0/0,J365/25"])
def test_next_transition_none_without_transitions(spec):
    assert TZ(spec).next_transition(D(2026, 6, 1)) is None
