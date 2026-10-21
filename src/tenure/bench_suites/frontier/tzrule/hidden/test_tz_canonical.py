"""정규형 str(tz), 같음과 해시."""

import pytest

from tzrule import TZ

CANON = [
    ("EST+05:00EDT4,M03.2.0/2,M11.1.0/02:00:00", "EST5EDT,M3.2.0,M11.1.0"),
    ("EST5EDT", "EST5EDT,M3.2.0,M11.1.0"),
    ("est5edt4", "est5edt,M3.2.0,M11.1.0"),
    ("<-03>3", "<-03>3"),
    ("<ABC>-0:30:00", "ABC-0:30"),
    ("UTC-0", "UTC0"),
    ("LMT-00:53:28", "LMT-0:53:28"),
    ("IST-1GMT0,M10.5.0,M3.5.0/1", "IST-1GMT0,M10.5.0,M3.5.0/1"),
    ("NST03:30NDT02:30", "NST3:30NDT,M3.2.0,M11.1.0"),
    ("<+1030>-10:30<+11>-11,M10.1.0,M4.1.0", "<+1030>-10:30<+11>-11,M10.1.0,M4.1.0"),
    ("XXX-3:30YYY-5", "XXX-3:30YYY-5,M3.2.0,M11.1.0"),
    ("<A-B+1>3<ZZ9>2,J1,J2", "<A-B+1>3<ZZ9>,J1,J2"),
    ("XXX3YYY2,J060/0:00,059/-0:30:00", "XXX3YYY,J60/0,59/-0:30"),
    ("XXX3YYY,M3.2.0/-0,M11.1.0/24:00:00", "XXX3YYY,M3.2.0/0,M11.1.0/24"),
    ("XXX3YYY,M3.2.0/167,M11.1.0/-167", "XXX3YYY,M3.2.0/167,M11.1.0/-167"),
    ("XXX3YYY,0/0:00:01,365/1:00:00", "XXX3YYY,0/0:00:01,365/1"),
    ("EST5EDT4,0/0,J365/25", "EST5EDT,0/0,J365/25"),
]


@pytest.mark.parametrize("spec,canon", CANON)
def test_canonical_string(spec, canon):
    assert str(TZ(spec)) == canon


def test_canonical_round_trip_and_spec_kept():
    for spec, canon in CANON:
        tz = TZ(spec)
        assert tz.spec == spec
        again = TZ(str(tz))
        assert str(again) == canon and again == tz


def test_equality_by_canonical_form():
    assert TZ("EST5EDT") == TZ("EST+05:00EDT4,M3.2.0/2,M11.1.0")
    assert TZ("EST5EDT") != TZ("EST5EDT,M3.2.0,M11.1.0/1")
    assert TZ("EST5EDT") != TZ("EST5")
    assert TZ("<ABC>3") == TZ("ABC3")
    assert TZ("UTC0") != "UTC0" and not (TZ("UTC0") == "UTC0")


def test_hash_follows_equality():
    a, b = TZ("GMT0BST,M3.5.0/1,M10.5.0"), TZ("GMT0BST-1,M3.5.0/01:00,M10.5.0/2")
    assert hash(a) == hash(b)
    assert len({a, b, TZ("CET-1CEST,M3.5.0,M10.5.0/3")}) == 2
