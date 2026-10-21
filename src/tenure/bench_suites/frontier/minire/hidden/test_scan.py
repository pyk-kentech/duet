"""findall · finditer · split: 빈 매치를 포함한 훑기 규칙과 결과 모양.

모든 기대값은 채점 때 파이썬 re 로 계산한다(신탁).
"""

import re

import pytest

import minire


def fl(mod, spec):
    v = 0
    for ch in spec:
        v |= getattr(mod, ch)
    return v


# ---------------------------------------------------------------- findall
@pytest.mark.parametrize("pat,s,flags", [
    ("a*?", "aa", ""),
    ("a??", "aa", ""),
    ("x*", "axbxx", ""),
    ("", "abc", ""),
    ("a|", "bab", ""),
    ("b*|a", "aab", ""),
    (r"\w*", "ab cd", ""),
    ("(?<=a)", "aab", ""),
    ("$|a", "a\n", ""),
    ("^|b", "ab\nb", "M"),
    (r"\b|a", "ab a", ""),
    ("(a)|(b)", "abc", ""),
    ("(a)?b", "bab", ""),
    ("(a)(b)?", "aab", ""),
    ("(a*)b", "aabb", ""),
    (r"(\d+)-(\d+)?", "1-2 3- 4-5", ""),
    (r"(?P<k>\w+)=(?P<v>[^;]*)", "a=1;b=;c=3", ""),
    ("(a|b)*", "abxba", ""),
    ("|a", "aa", ""),
    (r"\d*", "12a3", ""),
    ("(?<=a)a", "aaa", ""),
    ("(ab)*", "ababxab", ""),
    (r'(?:^|,)("(?:[^"]|"")*"|[^,]*)', 'a,"b,c",,d', ""),
    (r"\s*(?:(\d+)|(\w+)|(.))", "x = 12 + y", ""),
])
def test_findall(pat, s, flags):
    assert minire.compile(pat, fl(minire, flags)).findall(s) == re.compile(pat, fl(re, flags)).findall(s), pat


# ---------------------------------------------------------------- finditer
def _it(p, s):
    return [(m.span(), m.groups()) for m in p.finditer(s)]


@pytest.mark.parametrize("pat,s", [
    ("x*", "axx"),
    ("(?:)", ""),
    ("a*?", "ba"),
    (r"(a)|\b", "a b"),
    ("(?=(a))|a", "aa"),
])
def test_finditer(pat, s):
    assert _it(minire.compile(pat), s) == _it(re.compile(pat), s), pat


def test_finditer_basic():
    got = [(m.group(), m.start(), m.end()) for m in minire.finditer(r"\d+", "a1b22c333")]
    exp = [(m.group(), m.start(), m.end()) for m in re.finditer(r"\d+", "a1b22c333")]
    assert got == exp


# ---------------------------------------------------------------- split
@pytest.mark.parametrize("pat,s,maxsplit,flags", [
    (",", "a,b,,c", 0, ""),
    ("(,)", "a,b", 0, ""),
    ("(a)|(b)", "xaybz", 0, ""),
    ("x*", "axbc", 0, ""),
    (r"\b", "a b", 0, ""),
    ("", "abc", 0, ""),
    (",", "a,b,c", 1, ""),
    ("(-)", "a-b-c-d", 2, ""),
    ("x", "", 0, ""),
    ("x*", "", 0, ""),
    ("^", "a\nb", 0, "M"),
    ("a", "bab", -1, ""),
    ("x*", "abc", 2, ""),
    (r"\s*", "a b  c", 0, ""),
    (r"(\s)*", "a  b", 0, ""),
    ("(?:,)|(;)", "a,b;c", 0, ""),
    (r"(\W+)", "Words, words, words.", 0, ""),
    ("[a-z]", "aBc", 0, "I"),
    ("$", "a\nb\n", 0, "M"),
    ("(?=[A-Z])", "helloWorldFoo", 0, ""),
    ("(?<=,)|(?=,)", "a,b", 0, ""),
    ("(-)|(;)", "a-b;c-d", 2, ""),
])
def test_split(pat, s, maxsplit, flags):
    got = minire.compile(pat, fl(minire, flags)).split(s, maxsplit=maxsplit)
    assert got == re.compile(pat, fl(re, flags)).split(s, maxsplit=maxsplit), pat
