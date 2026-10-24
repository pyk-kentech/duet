"""지역 시각 <-> UTC: 틈·겹침과 fold, 음수 DST, 남반구, 해 넘김, 1년 내내 DST."""

from datetime import datetime, timedelta, timezone

import pytest

from tzrule import TZ


def H(h=0, m=0, s=0):
    return timedelta(hours=h, minutes=m, seconds=s)


D = datetime

NY = TZ("EST5EDT,M3.2.0,M11.1.0")
SYD = TZ("AEST-10AEDT,M10.1.0,M4.1.0/3")
DUB = TZ("IST-1GMT0,M10.5.0,M3.5.0/1")
NUUK = TZ("<-02>2<-01>,M3.5.0/-1,M10.5.0/0")
CHAT = TZ("<+1245>-12:45<+1345>,M9.5.0/2:45,M4.1.0/3:45")
LHI = TZ("<+1030>-10:30<+11>-11,M10.1.0,M4.1.0")
TROLL = TZ("<+00>0<+02>-2,M3.5.0/1,M10.5.0/3")
NEWYEAR = TZ("EST5EDT4,0/0,J365/24")        # 1월 1일 04:00~05:00 UTC 만 표준시
ALLYEAR = TZ("EST5EDT4,0/0,J365/25")
CROSS = TZ("XXX-10YYY,J1/5,J200")           # 1월 1일 05:00 지역 표준시에 시작
N365 = TZ("XXX3YYY,0,365")
SPILL = TZ("XXX3YYY,J60,J365/23")           # 끝: 다음 해 1월 1일 01:00 UTC
EVE = TZ("XXX-2YYY,J1/-1,J300")             # 시작: 전년도 12월 31일 23:00 지역 표준시
FIXED = TZ("<-03>3")


# ---------------------------------------------------------------- 보통 시각
@pytest.mark.parametrize("tz,local,off,name,dst", [
    (NY, D(2026, 7, 4, 12), H(-4), "EDT", H(1)),
    (NY, D(2026, 1, 15, 12), H(-5), "EST", H(0)),
    (SYD, D(2026, 1, 1, 0, 30), H(11), "AEDT", H(1)),
    (SYD, D(2026, 7, 1, 12), H(10), "AEST", H(0)),
    (DUB, D(2026, 7, 1, 12), H(1), "IST", H(0)),
    (DUB, D(2026, 1, 15, 12), H(0), "GMT", H(-1)),
    (CHAT, D(2026, 12, 25, 12), H(13, 45), "+1345", H(1)),
    (LHI, D(2026, 1, 1, 12), H(11), "+11", H(0, 30)),
    (TROLL, D(2026, 6, 1), H(2), "+02", H(2)),
    (FIXED, D(2026, 6, 1), H(-3), "-03", H(0)),
])
def test_ordinary_times(tz, local, off, name, dst):
    for fold in (0, 1):
        assert tz.utcoffset(local, fold) == off
        assert tz.tzname(local, fold) == name
        assert tz.dst(local, fold) == dst
        assert tz.to_utc(local, fold) == local - off
    assert not tz.is_gap(local) and not tz.is_ambiguous(local)


# ---------------------------------------------------------------- 뉴욕 틈·겹침
def test_ny_gap_fold_semantics():
    L = D(2026, 3, 8, 2, 30)
    assert NY.is_gap(L) and not NY.is_ambiguous(L)
    assert NY.utcoffset(L) == H(-5) and NY.utcoffset(L, fold=1) == H(-4)
    assert NY.to_utc(L) == D(2026, 3, 8, 7, 30) and NY.to_utc(L, fold=1) == D(2026, 3, 8, 6, 30)
    assert NY.tzname(L) == "EST" and NY.tzname(L, 1) == "EDT"


def test_ny_gap_boundaries():
    assert NY.is_gap(D(2026, 3, 8, 2, 0))
    assert NY.is_gap(D(2026, 3, 8, 2, 59, 59))
    assert not NY.is_gap(D(2026, 3, 8, 3, 0))
    assert not NY.is_gap(D(2026, 3, 8, 1, 59, 59))
    assert NY.to_utc(D(2026, 3, 8, 3, 0)) == D(2026, 3, 8, 7, 0)
    assert NY.to_utc(D(2026, 3, 8, 1, 59, 59), fold=1) == D(2026, 3, 8, 6, 59, 59)


def test_ny_overlap_fold_semantics():
    L = D(2026, 11, 1, 1, 30)
    assert NY.is_ambiguous(L) and not NY.is_gap(L)
    assert NY.utcoffset(L) == H(-4) and NY.utcoffset(L, 1) == H(-5)
    assert NY.to_utc(L) == D(2026, 11, 1, 5, 30) and NY.to_utc(L, 1) == D(2026, 11, 1, 6, 30)
    assert NY.tzname(L) == "EDT" and NY.tzname(L, 1) == "EST"
    assert NY.dst(L) == H(1) and NY.dst(L, 1) == H(0)


def test_ny_overlap_boundaries():
    assert NY.is_ambiguous(D(2026, 11, 1, 1, 0))
    assert not NY.is_ambiguous(D(2026, 11, 1, 0, 59, 59))
    assert not NY.is_ambiguous(D(2026, 11, 1, 2, 0))
    assert NY.to_utc(D(2026, 11, 1, 2, 0), fold=0) == D(2026, 11, 1, 7, 0)
    assert NY.to_utc(D(2026, 11, 1, 0, 59, 59), fold=1) == D(2026, 11, 1, 4, 59, 59)


def test_local_fold_attribute_is_ignored():
    L = D(2026, 11, 1, 1, 30, fold=1)
    assert NY.utcoffset(L) == H(-4)
    assert NY.to_utc(L) == D(2026, 11, 1, 5, 30)
    assert NY.tzname(L) == "EDT"
    assert NY.to_utc(D(2026, 3, 8, 2, 30, fold=1)) == D(2026, 3, 8, 7, 30)


def test_local_fold_attribute_is_ignored_with_explicit_fold():
    assert NY.utcoffset(D(2026, 11, 1, 1, 30, fold=0), 1) == H(-5)
    assert NY.tzname(D(2026, 3, 8, 2, 30, fold=0), fold=1) == "EDT"
    assert NY.dst(D(2026, 3, 8, 2, 30, fold=1)) == H(0)


@pytest.mark.parametrize("method", ["utcoffset", "to_utc", "tzname", "dst", "is_gap", "is_ambiguous"])
def test_aware_local_rejected(method):
    with pytest.raises(ValueError):
        getattr(NY, method)(D(2026, 7, 1, tzinfo=timezone.utc))


@pytest.mark.parametrize("fold", [2, -1])
def test_bad_fold_rejected(fold):
    with pytest.raises(ValueError):
        NY.utcoffset(D(2026, 7, 1), fold)
    with pytest.raises(ValueError):
        NY.to_utc(D(2026, 11, 1, 1, 30), fold)


@pytest.mark.parametrize("utc,local,fold", [
    (D(2026, 11, 1, 5, 30), D(2026, 11, 1, 1, 30), 0),
    (D(2026, 11, 1, 5, 59, 59), D(2026, 11, 1, 1, 59, 59), 0),
    (D(2026, 11, 1, 6, 0), D(2026, 11, 1, 1, 0), 1),
    (D(2026, 11, 1, 6, 30), D(2026, 11, 1, 1, 30), 1),
    (D(2026, 11, 1, 6, 59, 59), D(2026, 11, 1, 1, 59, 59), 1),
    (D(2026, 11, 1, 7, 0), D(2026, 11, 1, 2, 0), 0),
    (D(2026, 3, 8, 6, 59, 59), D(2026, 3, 8, 1, 59, 59), 0),
    (D(2026, 3, 8, 7, 0), D(2026, 3, 8, 3, 0), 0),
])
def test_ny_from_utc(utc, local, fold):
    assert NY.from_utc(utc) == (local, fold)


def test_from_utc_accepts_aware_and_returns_naive():
    loc, fold = NY.from_utc(D(2026, 11, 1, 6, 30, tzinfo=timezone.utc))
    assert (loc, fold) == (D(2026, 11, 1, 1, 30), 1) and loc.tzinfo is None
    loc, fold = NY.from_utc(D(2026, 11, 1, 15, 30, tzinfo=timezone(H(9))))
    assert (loc, fold) == (D(2026, 11, 1, 1, 30), 1) and loc.tzinfo is None


# ---------------------------------------------------------------- 음수 DST (더블린)
def test_dublin_spring_gap():
    L = D(2026, 3, 29, 1, 30)
    assert DUB.is_gap(L)
    assert DUB.to_utc(L) == D(2026, 3, 29, 1, 30)            # fold=0: 전이 전 GMT(0)
    assert DUB.to_utc(L, 1) == D(2026, 3, 29, 0, 30)         # fold=1: 전이 후 IST(+1)
    assert DUB.tzname(L) == "GMT" and DUB.tzname(L, 1) == "IST"


def test_dublin_autumn_overlap():
    L = D(2026, 10, 25, 1, 30)
    assert DUB.is_ambiguous(L)
    assert DUB.utcoffset(L) == H(1) and DUB.utcoffset(L, 1) == H(0)
    assert DUB.dst(L) == H(0) and DUB.dst(L, 1) == H(-1)
    assert DUB.from_utc(D(2026, 10, 25, 0, 30)) == (L, 0)
    assert DUB.from_utc(D(2026, 10, 25, 1, 30)) == (L, 1)
    assert DUB.from_utc(D(2026, 10, 25, 2, 0)) == (D(2026, 10, 25, 2, 0), 0)


# ---------------------------------------------------------------- 남반구 (시드니)
def test_sydney_gap_and_overlap():
    assert SYD.is_gap(D(2026, 10, 4, 2, 30))
    assert SYD.to_utc(D(2026, 10, 4, 2, 30)) == D(2026, 10, 3, 16, 30)
    assert SYD.to_utc(D(2026, 10, 4, 2, 30), 1) == D(2026, 10, 3, 15, 30)
    assert SYD.is_ambiguous(D(2026, 4, 5, 2, 30))
    assert SYD.to_utc(D(2026, 4, 5, 2, 30)) == D(2026, 4, 4, 15, 30)
    assert SYD.to_utc(D(2026, 4, 5, 2, 30), 1) == D(2026, 4, 4, 16, 30)


def test_sydney_from_utc_second_pass_and_new_year():
    assert SYD.from_utc(D(2026, 4, 4, 16, 30)) == (D(2026, 4, 5, 2, 30), 1)
    assert SYD.from_utc(D(2026, 4, 4, 15, 30)) == (D(2026, 4, 5, 2, 30), 0)
    assert SYD.from_utc(D(2025, 12, 31, 13, 30)) == (D(2026, 1, 1, 0, 30), 0)


# ---------------------------------------------------------------- 분 단위 오프셋·전이
def test_chatham_gap_and_overlap():
    assert CHAT.is_gap(D(2026, 9, 27, 2, 45)) and CHAT.is_gap(D(2026, 9, 27, 3, 44, 59))
    assert not CHAT.is_gap(D(2026, 9, 27, 3, 45)) and not CHAT.is_gap(D(2026, 9, 27, 2, 44, 59))
    assert CHAT.to_utc(D(2026, 9, 27, 3, 0)) == D(2026, 9, 26, 14, 15)
    assert CHAT.to_utc(D(2026, 9, 27, 3, 0), 1) == D(2026, 9, 26, 13, 15)
    assert CHAT.is_ambiguous(D(2026, 4, 5, 2, 45)) and not CHAT.is_ambiguous(D(2026, 4, 5, 3, 45))
    assert CHAT.to_utc(D(2026, 4, 5, 3, 0)) == D(2026, 4, 4, 13, 15)
    assert CHAT.to_utc(D(2026, 4, 5, 3, 0), 1) == D(2026, 4, 4, 14, 15)


def test_lord_howe_half_hour_dst():
    assert LHI.is_gap(D(2026, 10, 4, 2, 15)) and not LHI.is_gap(D(2026, 10, 4, 2, 30))
    assert LHI.to_utc(D(2026, 10, 4, 2, 15)) == D(2026, 10, 3, 15, 45)
    assert LHI.to_utc(D(2026, 10, 4, 2, 15), 1) == D(2026, 10, 3, 15, 15)
    assert LHI.is_ambiguous(D(2026, 4, 5, 1, 45)) and not LHI.is_ambiguous(D(2026, 4, 5, 1, 15))
    assert LHI.from_utc(D(2026, 4, 4, 15, 15)) == (D(2026, 4, 5, 1, 45), 1)
    assert LHI.from_utc(D(2026, 4, 4, 14, 45)) == (D(2026, 4, 5, 1, 45), 0)


def test_troll_two_hour_dst():
    assert TROLL.is_gap(D(2026, 3, 29, 1, 0)) and TROLL.is_gap(D(2026, 3, 29, 2, 59, 59))
    assert TROLL.to_utc(D(2026, 3, 29, 2, 0)) == D(2026, 3, 29, 2, 0)
    assert TROLL.to_utc(D(2026, 3, 29, 2, 0), 1) == D(2026, 3, 29, 0, 0)
    assert TROLL.from_utc(D(2026, 10, 25, 0, 59, 59)) == (D(2026, 10, 25, 2, 59, 59), 0)
    assert TROLL.from_utc(D(2026, 10, 25, 1, 0)) == (D(2026, 10, 25, 1, 0), 1)
    assert TROLL.from_utc(D(2026, 10, 25, 2, 59, 59)) == (D(2026, 10, 25, 2, 59, 59), 1)
    assert TROLL.from_utc(D(2026, 10, 25, 3, 0)) == (D(2026, 10, 25, 3, 0), 0)


# ---------------------------------------------------------------- 날짜를 넘는 틈·겹침 (누크)
def test_nuuk_gap_on_previous_calendar_day():
    assert NUUK.is_gap(D(2026, 3, 28, 23, 30)) and not NUUK.is_gap(D(2026, 3, 29, 0, 0))
    assert NUUK.to_utc(D(2026, 3, 28, 23, 30)) == D(2026, 3, 29, 1, 30)
    assert NUUK.to_utc(D(2026, 3, 28, 23, 30), 1) == D(2026, 3, 29, 0, 30)


def test_nuuk_overlap_on_previous_calendar_day():
    assert NUUK.is_ambiguous(D(2026, 10, 24, 23, 30))
    assert NUUK.to_utc(D(2026, 10, 24, 23, 30)) == D(2026, 10, 25, 0, 30)
    assert NUUK.to_utc(D(2026, 10, 24, 23, 30), 1) == D(2026, 10, 25, 1, 30)
    assert NUUK.from_utc(D(2026, 10, 25, 1, 30)) == (D(2026, 10, 24, 23, 30), 1)


# ---------------------------------------------------------------- 해 넘김
def test_new_year_overlap_then_gap():
    assert NEWYEAR.is_ambiguous(D(2025, 12, 31, 23, 0)) and NEWYEAR.is_ambiguous(D(2025, 12, 31, 23, 30))
    assert not NEWYEAR.is_ambiguous(D(2025, 12, 31, 22, 59, 59))
    assert NEWYEAR.is_gap(D(2026, 1, 1, 0, 0)) and NEWYEAR.is_gap(D(2026, 1, 1, 0, 30))
    assert not NEWYEAR.is_gap(D(2026, 1, 1, 1, 0)) and not NEWYEAR.is_ambiguous(D(2026, 1, 1, 0, 0))


def test_new_year_overlap_conversions():
    L = D(2025, 12, 31, 23, 30)
    assert NEWYEAR.to_utc(L) == D(2026, 1, 1, 3, 30) and NEWYEAR.to_utc(L, 1) == D(2026, 1, 1, 4, 30)
    assert NEWYEAR.tzname(L) == "EDT" and NEWYEAR.tzname(L, 1) == "EST"
    assert NEWYEAR.from_utc(D(2026, 1, 1, 4, 30)) == (L, 1)
    assert NEWYEAR.from_utc(D(2026, 1, 1, 3, 30)) == (L, 0)


def test_new_year_gap_conversions():
    L = D(2026, 1, 1, 0, 30)
    assert NEWYEAR.utcoffset(L) == H(-5) and NEWYEAR.utcoffset(L, 1) == H(-4)
    assert NEWYEAR.to_utc(L) == D(2026, 1, 1, 5, 30) and NEWYEAR.to_utc(L, 1) == D(2026, 1, 1, 4, 30)
    assert NEWYEAR.from_utc(D(2026, 1, 1, 5, 0)) == (D(2026, 1, 1, 1, 0), 0)


def test_cross_year_start_gap_on_january_first():
    L = D(2027, 1, 1, 5, 30)
    assert CROSS.is_gap(L)
    assert CROSS.to_utc(L) == D(2026, 12, 31, 19, 30) and CROSS.to_utc(L, 1) == D(2026, 12, 31, 18, 30)
    assert CROSS.from_utc(D(2026, 12, 31, 19, 30)) == (D(2027, 1, 1, 6, 30), 0)
    assert CROSS.utcoffset(D(2027, 1, 1, 12)) == H(11)
    assert CROSS.utcoffset(D(2027, 1, 1, 4, 59)) == H(10)


def test_end_rule_spill_local_and_from_utc():
    assert SPILL.utcoffset(D(2025, 12, 31, 21)) == H(-2)
    assert SPILL.is_ambiguous(D(2025, 12, 31, 22, 30))
    assert SPILL.utcoffset(D(2025, 12, 31, 23, 30)) == H(-3)
    assert SPILL.to_utc(D(2025, 12, 31, 22, 30), 1) == D(2026, 1, 1, 1, 30)


def test_end_rule_spill_from_utc():
    assert SPILL.from_utc(D(2026, 1, 1, 0, 30)) == (D(2025, 12, 31, 22, 30), 0)
    assert SPILL.from_utc(D(2026, 1, 1, 1, 30)) == (D(2025, 12, 31, 22, 30), 1)
    assert SPILL.from_utc(D(2026, 1, 1, 2, 0)) == (D(2025, 12, 31, 23, 0), 0)


def test_new_year_eve_gap_belongs_to_next_years_rule():
    assert EVE.is_gap(D(2026, 12, 31, 23, 30)) and not EVE.is_gap(D(2026, 12, 31, 22, 59))
    assert EVE.to_utc(D(2026, 12, 31, 23, 30)) == D(2026, 12, 31, 21, 30)
    assert EVE.to_utc(D(2026, 12, 31, 23, 30), 1) == D(2026, 12, 31, 20, 30)
    assert EVE.utcoffset(D(2027, 1, 1, 0, 30)) == H(3)
    assert EVE.from_utc(D(2026, 12, 31, 21, 0)) == (D(2027, 1, 1, 0, 0), 0)


def test_all_year_dst_has_no_gap_or_overlap():
    for L in (D(2025, 12, 31, 23, 30), D(2026, 1, 1, 0, 30), D(2026, 7, 1)):
        assert ALLYEAR.utcoffset(L) == H(-4) and ALLYEAR.utcoffset(L, 1) == H(-4)
        assert ALLYEAR.tzname(L) == "EDT" and ALLYEAR.dst(L) == H(1)
        assert not ALLYEAR.is_gap(L) and not ALLYEAR.is_ambiguous(L)
    assert ALLYEAR.from_utc(D(2026, 1, 1, 4, 30)) == (D(2026, 1, 1, 0, 30), 0)


def test_n365_end_rule_in_leap_and_common_years():
    # 2024(윤년): 365 = 12월 31일 → 12월 31일 오후는 표준시
    assert N365.is_ambiguous(D(2024, 12, 31, 1, 30))
    assert N365.utcoffset(D(2024, 12, 31, 12)) == H(-3)
    assert N365.is_gap(D(2025, 1, 1, 2, 30))
    # 2025(평년): 365 = 2026년 1월 1일 → 12월 31일 오후는 아직 DST
    assert N365.utcoffset(D(2025, 12, 31, 12)) == H(-2)
    assert N365.is_ambiguous(D(2026, 1, 1, 1, 30)) and N365.is_gap(D(2026, 1, 1, 2, 30))


def test_fixed_zone_from_utc_and_to_utc():
    assert FIXED.from_utc(D(2026, 3, 1, 1)) == (D(2026, 2, 28, 22), 0)
    assert FIXED.to_utc(D(2026, 2, 28, 22)) == D(2026, 3, 1, 1)


# ---------------------------------------------------------------- 왕복
def _scan(year):
    t = D(year, 1, 1) - H(30)
    end = D(year + 1, 1, 1) + H(30)
    while t < end:
        yield t
        t += H(0, 47, 13)


@pytest.mark.parametrize("tz", [NY, SYD, DUB, NUUK, CHAT, LHI, TROLL, NEWYEAR, CROSS, N365, SPILL, EVE],
                         ids=["ny", "syd", "dub", "nuuk", "chat", "lhi", "troll", "newyear", "cross", "n365",
                              "spill", "eve"])
def test_round_trip_every_instant(tz):
    for u in _scan(2026):
        local, fold = tz.from_utc(u)
        assert tz.to_utc(local, fold) == u, (u, local, fold)
        assert tz.utcoffset(local, fold) == local - u
        assert not tz.is_gap(local)
        if fold == 1:
            assert tz.is_ambiguous(local)
