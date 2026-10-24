"""TZ.tzinfo(): datetime 과 함께 쓰기 (PEP 495 fold)."""

from datetime import datetime, time, timedelta, timezone, tzinfo

import pytest

from tzrule import TZ


def H(h=0, m=0, s=0):
    return timedelta(hours=h, minutes=m, seconds=s)


UTC = timezone.utc
NY = TZ("EST5EDT,M3.2.0,M11.1.0")
NYI = NY.tzinfo()


def test_same_tzinfo_object_each_call():
    assert isinstance(NYI, tzinfo)
    assert NY.tzinfo() is NYI


def test_aware_datetime_basic_values():
    d = datetime(2026, 7, 4, 12, tzinfo=NYI)
    assert d.utcoffset() == H(-4) and d.tzname() == "EDT" and d.dst() == H(1)
    w = datetime(2026, 1, 15, 12, tzinfo=NYI)
    assert w.utcoffset() == H(-5) and w.tzname() == "EST" and w.dst() == H(0)


def test_dt_fold_is_used_in_overlap():
    d = datetime(2026, 11, 1, 1, 30, tzinfo=NYI)
    assert d.utcoffset() == H(-4) and d.tzname() == "EDT"
    d1 = d.replace(fold=1)
    assert d1.utcoffset() == H(-5) and d1.tzname() == "EST" and d1.dst() == H(0)


@pytest.mark.parametrize("local,fold,utc", [
    (datetime(2026, 11, 1, 1, 30), 0, datetime(2026, 11, 1, 5, 30)),
    (datetime(2026, 11, 1, 1, 30), 1, datetime(2026, 11, 1, 6, 30)),
    (datetime(2026, 3, 8, 2, 30), 0, datetime(2026, 3, 8, 7, 30)),
    (datetime(2026, 3, 8, 2, 30), 1, datetime(2026, 3, 8, 6, 30)),
])
def test_astimezone_to_utc(local, fold, utc):
    d = local.replace(tzinfo=NYI, fold=fold)
    assert d.astimezone(UTC) == utc.replace(tzinfo=UTC)


@pytest.mark.parametrize("utc,wall,fold,name", [
    (datetime(2026, 11, 1, 5, 30), datetime(2026, 11, 1, 1, 30), 0, "EDT"),
    (datetime(2026, 11, 1, 6, 30), datetime(2026, 11, 1, 1, 30), 1, "EST"),
    (datetime(2026, 3, 8, 7, 0), datetime(2026, 3, 8, 3, 0), 0, "EDT"),
])
def test_astimezone_from_utc_sets_fold(utc, wall, fold, name):
    d = utc.replace(tzinfo=UTC).astimezone(NYI)
    assert d.tzinfo is NYI
    assert d.replace(tzinfo=None) == wall and d.fold == fold and d.tzname() == name


def test_fromutc_direct_call():
    d = NYI.fromutc(datetime(2026, 11, 1, 6, 30, tzinfo=NYI))
    assert d.replace(tzinfo=None) == datetime(2026, 11, 1, 1, 30) and d.fold == 1 and d.tzinfo is NYI


def test_fromutc_rejects_other_tzinfo():
    with pytest.raises(ValueError):
        NYI.fromutc(datetime(2026, 1, 1, tzinfo=UTC))


def test_none_argument_returns_none():
    assert NYI.utcoffset(None) is None
    assert NYI.dst(None) is None
    assert NYI.tzname(None) is None
    assert time(12, tzinfo=NYI).utcoffset() is None


def test_timestamp_uses_fold():
    a = datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=NYI).timestamp()
    assert a == datetime(2026, 11, 1, 6, 30, tzinfo=UTC).timestamp()


def test_negative_dst_through_tzinfo():
    dub = TZ("IST-1GMT0,M10.5.0,M3.5.0/1").tzinfo()
    assert datetime(2026, 1, 15, tzinfo=dub).dst() == H(-1)
    assert datetime(2026, 7, 15, tzinfo=dub).dst() == H(0)
    d = datetime(2026, 10, 25, 1, 30, tzinfo=UTC).astimezone(dub)
    assert d.replace(tzinfo=None) == datetime(2026, 10, 25, 1, 30) and d.fold == 1 and d.tzname() == "GMT"


def test_southern_and_new_year_through_tzinfo():
    syd = TZ("AEST-10AEDT,M10.1.0,M4.1.0/3").tzinfo()
    d = datetime(2026, 4, 4, 16, 30, tzinfo=UTC).astimezone(syd)
    assert d.replace(tzinfo=None) == datetime(2026, 4, 5, 2, 30) and d.fold == 1 and d.tzname() == "AEST"
    ny4 = TZ("EST5EDT4,0/0,J365/24").tzinfo()
    e = datetime(2026, 1, 1, 4, 30, tzinfo=UTC).astimezone(ny4)
    assert e.replace(tzinfo=None) == datetime(2025, 12, 31, 23, 30) and e.fold == 1
    assert e.utcoffset() == H(-5)


def test_spilled_end_rule_through_tzinfo():
    tzi = TZ("XXX3YYY,J60,J365/23").tzinfo()
    d = datetime(2026, 1, 1, 1, 30, tzinfo=UTC).astimezone(tzi)
    assert d.replace(tzinfo=None) == datetime(2025, 12, 31, 22, 30) and d.fold == 1 and d.tzname() == "XXX"
    e = datetime(2026, 1, 1, 0, 30, tzinfo=UTC).astimezone(tzi)
    assert e.replace(tzinfo=None) == datetime(2025, 12, 31, 22, 30) and e.fold == 0 and e.tzname() == "YYY"
