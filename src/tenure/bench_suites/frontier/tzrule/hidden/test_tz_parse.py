"""TZ 문자열 해석: 이름, 오프셋 부호, 기본값, 오류."""

import re
from datetime import timedelta
from pathlib import Path

import pytest

import tzrule
from tzrule import TZ


def H(h=0, m=0, s=0):
    return timedelta(hours=h, minutes=m, seconds=s)


VALID = [
    # spec, std_abbr, std_offset, dst_abbr, dst_offset
    ("EST5EDT,M3.2.0,M11.1.0", "EST", H(-5), "EDT", H(-4)),
    ("GMT0BST,M3.5.0/1,M10.5.0", "GMT", H(0), "BST", H(1)),
    ("AEST-10AEDT,M10.1.0,M4.1.0/3", "AEST", H(10), "AEDT", H(11)),
    ("IST-1GMT0,M10.5.0,M3.5.0/1", "IST", H(1), "GMT", H(0)),
    ("<-02>2<-01>,M3.5.0/-1,M10.5.0/0", "-02", H(-2), "-01", H(-1)),
    ("<+1245>-12:45<+1345>,M9.5.0/2:45,M4.1.0/3:45", "+1245", H(12, 45), "+1345", H(13, 45)),
    ("<-03>3", "-03", H(-3), None, None),
    ("<+0330>-3:30", "+0330", H(3, 30), None, None),
    ("NST3:30NDT,M3.2.0,M11.1.0", "NST", -H(3, 30), "NDT", -H(2, 30)),
    ("<+1030>-10:30<+11>-11,M10.1.0,M4.1.0", "+1030", H(10, 30), "+11", H(11)),
    ("<+00>0<+02>-2,M3.5.0/1,M10.5.0/3", "+00", H(0), "+02", H(2)),
    ("EST+5EDT", "EST", H(-5), "EDT", H(-4)),
    ("EST05EDT04", "EST", H(-5), "EDT", H(-4)),
    ("LMT-0:53:28", "LMT", H(0, 53, 28), None, None),
    ("<+0030>-0:30", "+0030", H(0, 30), None, None),
    ("XXX0:30", "XXX", -H(0, 30), None, None),
    ("est5edt", "est", H(-5), "edt", H(-4)),
    ("ABCDEFGH-23:59:59", "ABCDEFGH", H(23, 59, 59), None, None),
    ("<A-B+1>3<ZZ9>2,J1,J2", "A-B+1", H(-3), "ZZ9", H(-2)),
    ("XXX-3:30YYY", "XXX", H(3, 30), "YYY", H(4, 30)),
    ("<-0130>1:30<-0030>", "-0130", -H(1, 30), "-0030", -H(0, 30)),
    ("AAA-5BBB-6:30,J100/0,J280/23:59:59", "AAA", H(5), "BBB", H(6, 30)),
    ("XXX3YYY,M3.2.0/+2,M11.1.0/002", "XXX", H(-3), "YYY", H(-2)),
]


@pytest.mark.parametrize("spec,std_abbr,std_off,dst_abbr,dst_off", VALID)
def test_valid_spec_attributes(spec, std_abbr, std_off, dst_abbr, dst_off):
    tz = TZ(spec)
    assert tz.std_abbr == std_abbr
    assert tz.std_offset == std_off
    assert tz.dst_abbr == dst_abbr
    assert tz.dst_offset == dst_off


def test_spec_attribute_is_original_string():
    s = "<+1245>-12:45<+1345>,M9.5.0/2:45,M4.1.0/3:45"
    assert TZ(s).spec == s


def test_offsets_are_timedelta():
    tz = TZ("EST5EDT,M3.2.0,M11.1.0")
    assert isinstance(tz.std_offset, timedelta) and isinstance(tz.dst_offset, timedelta)


INVALID = [
    "",
    " EST5",
    "EST5 ",
    "EST5\n",
    "EST5EDT,M3.2.0,M11.1.0\n",
    "EST",
    "ES5",
    "5EST",
    "<ES>5",
    "<+3>-3",
    "<EST5",
    "<E_T>5",
    "<>5",
    "EST5ED",
    "EST5EDT,",
    "EST5EDT,M3.2.0",
    "EST5EDT,M3.2.0,M11.1.0,",
    "EST5,M3.2.0,M11.1.0",
    "EST5EDT4X",
    "EST+-5",
    "EST123",
    "EST5:3",
    "EST5:60",
    "EST5:30:60",
    "EST5EDT,M13.1.0,M11.1.0",
    "EST5EDT,M3.0.0,M11.1.0",
    "EST5EDT,M3.2.7,M11.1.0",
    "EST5EDT,M3.2,M11.1.0",
    "EST5EDT,M3.02.0,M11.1.0",
    "EST5EDT,M3.2.00,M11.1.0",
    "EST5EDT,M003.2.0,M11.1.0",
    "EST5EDT,J0,J100",
    "EST5EDT,J366,J100",
    "EST5EDT,366,100",
    "EST5EDT,0060,100",
    "EST5EDT,J,J100",
    "EST5EDT,m3.2.0,m11.1.0",
    "EST5EDT,M3.2.0/168,M11.1.0",
    "EST5EDT,M3.2.0/-168,M11.1.0",
    "EST5EDT,M3.2.0/0167,M11.1.0",
    "EST5EDT,M3.2.0/2:60,M11.1.0",
    "EST5EDT,M3.2.0/2:5,M11.1.0",
    "EST5EDT,M3.2.0/,M11.1.0",
    "EST5EDT,M3.2.0/+,M11.1.0",
]


@pytest.mark.parametrize("spec", INVALID)
def test_invalid_spec_raises_value_error(spec):
    with pytest.raises(ValueError):
        TZ(spec)


@pytest.mark.parametrize("spec", ["EST24", "EST24:00", "XXX-24YYY", "EST5EDT24"])
def test_offset_hours_24_or_more_rejected(spec):
    with pytest.raises(ValueError):
        TZ(spec)


@pytest.mark.parametrize("spec", ["XXX-23YYY", "XXX-23:30YYY"])
def test_default_dst_offset_reaching_24h_rejected(spec):
    with pytest.raises(ValueError):
        TZ(spec)


@pytest.mark.parametrize("spec", ["AAA3BBB3,J1,J100", "AAA-1BBB-1", "AAA-1BBB-1:00:00,M3.5.0,M10.5.0"])
def test_dst_offset_equal_to_std_rejected(spec):
    with pytest.raises(ValueError):
        TZ(spec)


@pytest.mark.parametrize("spec", [
    "EST٥",                       # ARABIC-INDIC DIGIT FIVE
    "EST５EDT",                    # FULLWIDTH DIGIT FIVE
    "ÉST5",                       # É
    "EST5EDT,J٦٠,J300",      # J٦٠
    "<ÉST>5",
])
def test_non_ascii_digits_and_letters_rejected(spec):
    with pytest.raises(ValueError):
        TZ(spec)


@pytest.mark.parametrize("spec", [None, 5, b"EST5"])
def test_non_string_spec_is_type_error(spec):
    with pytest.raises(TypeError):
        TZ(spec)


def test_rule_time_hours_may_exceed_24_but_offset_may_not():
    assert TZ("EST5EDT,M3.2.0/24,M11.1.0/167").dst_offset == H(-4)
    with pytest.raises(ValueError):
        TZ("EST005EDT")


def test_package_does_not_use_tz_database():
    pkg = Path(tzrule.__file__).parent
    pat = re.compile(r"^\s*(import|from)\s+(zoneinfo|pytz|dateutil)\b|\btzset\s*\(", re.M)
    for f in pkg.rglob("*.py"):
        assert not pat.search(f.read_text(encoding="utf-8")), f.name
