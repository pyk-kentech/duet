from datetime import time

import pytest

from booking import format_hours, parse_hours


def test_parse_basic():
    h = parse_hours("mon-fri 08:00-20:00; sat 10:00-14:00")
    assert h[0] == (time(8), time(20)) and h[4] == (time(8), time(20)) and h[5] == (time(10), time(14))
    assert 6 not in h


def test_parse_list_and_empty():
    h = parse_hours("mon,wed 09:00-12:00")
    assert sorted(h) == [0, 2]
    assert parse_hours("") == {}


@pytest.mark.parametrize("spec", ["mon 25:00-26:00", "mon 09:00-09:00", "xyz 09:00-10:00", "fri-mon 09:00-10:00",
                                  "mon 09:10-10:00", "mon 09:00", "mon 09:00-10:00; mon 11:00-12:00"])
def test_parse_errors(spec):
    with pytest.raises(ValueError):
        parse_hours(spec)


def test_format_groups_days():
    assert format_hours(parse_hours("sat 10:00-14:00; mon-fri 08:00-20:00")) == "mon-fri 08:00-20:00; sat 10:00-14:00"
    assert format_hours(parse_hours("mon,wed 09:00-12:00")) == "mon 09:00-12:00; wed 09:00-12:00"
