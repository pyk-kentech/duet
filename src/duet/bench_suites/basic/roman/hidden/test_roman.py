import subprocess
import sys

import pytest

import roman

CASES = {1: "I", 3: "III", 4: "IV", 9: "IX", 14: "XIV", 40: "XL", 90: "XC", 400: "CD", 444: "CDXLIV",
         900: "CM", 1994: "MCMXCIV", 2024: "MMXXIV", 3888: "MMMDCCCLXXXVIII", 3999: "MMMCMXCIX"}


@pytest.mark.parametrize("n,s", CASES.items())
def test_to_roman(n, s):
    assert roman.to_roman(n) == s


@pytest.mark.parametrize("n,s", CASES.items())
def test_from_roman(n, s):
    assert roman.from_roman(s) == n


def test_roundtrip_all():
    for n in range(1, 4000):
        assert roman.from_roman(roman.to_roman(n)) == n


@pytest.mark.parametrize("bad", [0, -1, 4000, True, False, 3.0, "5", None])
def test_to_roman_invalid(bad):
    with pytest.raises(ValueError):
        roman.to_roman(bad)


@pytest.mark.parametrize("bad", ["", "iv", "Iv", "IIII", "VV", "IC", "IIV", "XM", "MMMM", "VX", "LL",
                                 " IV", "IV ", "ABC", "I V", None, 5])
def test_from_roman_invalid(bad):
    with pytest.raises(ValueError):
        roman.from_roman(bad)


def run(*args):
    return subprocess.run([sys.executable, "-m", "roman", *args], capture_output=True, text=True, timeout=30)


def test_cli_both_directions():
    r = run("1994")
    assert r.returncode == 0 and r.stdout.strip() == "MCMXCIV"
    r = run("MCMXCIV")
    assert r.returncode == 0 and r.stdout.strip() == "1994"


@pytest.mark.parametrize("bad", ["IIII", "0", "4000", "hello"])
def test_cli_error(bad):
    r = run(bad)
    assert r.returncode == 1 and r.stderr.strip() and not r.stdout.strip()
