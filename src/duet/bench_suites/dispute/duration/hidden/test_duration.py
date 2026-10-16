import random

import pytest

import duration


@pytest.mark.parametrize("text,sec", [("1h30m", 5400), ("2d", 172800), ("45s", 45), ("0s", 0), ("1d2h3m4s", 93784),
                                      ("05m", 300), ("0d0h0m0s", 0), ("100h", 360000), ("1d4s", 86404),
                                      ("999999999999d", 999999999999 * 86400)])
def test_parse_valid(text, sec):
    assert duration.parse(text) == sec


@pytest.mark.parametrize("bad", ["", "1h 30m", " 1h", "1h ", "1H", "1D", "30m1h", "1h1h", "90", "1.5h", "-1h", "+1h",
                                 "1w", "1ms", "h", "1hm", "1h30", "١h", "1_000s", "1h\n", "0x10s", "s1"])
def test_parse_rejects(bad):
    with pytest.raises(ValueError):
        duration.parse(bad)


@pytest.mark.parametrize("bad", [None, 5, 1.5, b"1h"])
def test_parse_type_error(bad):
    with pytest.raises(TypeError):
        duration.parse(bad)


@pytest.mark.parametrize("sec,text", [(5400, "1h30m"), (93784, "1d2h3m4s"), (86400, "1d"), (0, "0s"), (59, "59s"),
                                      (60, "1m"), (3601, "1h1s"), (90061, "1d1h1m1s")])
def test_format(sec, text):
    assert duration.format(sec) == text


def test_format_errors():
    with pytest.raises(ValueError):
        duration.format(-1)
    for bad in (1.0, True, False, "5", None):
        with pytest.raises(TypeError):
            duration.format(bad)


def test_roundtrip():
    rnd = random.Random(7)
    for n in [0, 1, 59, 60, 3599, 3600, 86399, 86400, 10 ** 12] + [rnd.randrange(0, 10 ** 9) for _ in range(300)]:
        assert duration.parse(duration.format(n)) == n
