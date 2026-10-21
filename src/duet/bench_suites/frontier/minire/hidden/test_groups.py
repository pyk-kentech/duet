"""그룹: 캡처·반복된 그룹·역추적과 캡처·빈 반복·역참조·전방/후방 탐색·lastindex.

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


def spans(m, n):
    if m is None:
        return None
    return [m.span(i) for i in range(n + 1)]


def check(op, pat, s, flags=""):
    rp = re.compile(pat, fl(re, flags))
    mp = minire.compile(pat, fl(minire, flags))
    n = rp.groups
    assert spans(getattr(mp, op)(s), n) == spans(getattr(rp, op)(s), n), (op, pat, s, flags)


# ---------------------------------------------------------------- 캡처와 반복된 그룹
@pytest.mark.parametrize("pat,s", [
    (r"((a)(b(c)))", "abc"),
    (r"(\w)+", "abc"),
    ("(a|b)*", "abba"),
    ("(x)?y", "y"),
    ("(a)|(b)", "b"),
    ("(?:(a)|(b))+", "abab"),
    ("(?:(a)|(b))+", "aab"),
    ("(?:(a)|b)*", "ab"),
    ("(?:(a)|(b)|c)+", "abc"),
    ("(?:(a)|(b)){2}", "ba"),
    (r"(?:(\d)|([a-z]))+", "1a2"),
    ("(a(b)?)+", "aba"),
])
def test_repeated_groups_keep_last_values(pat, s):
    check("match", pat, s)


# ---------------------------------------------------------------- 역추적으로 버린 경로의 캡처는 남지 않는다
@pytest.mark.parametrize("pat,s", [
    ("(?:(a)b|ac)", "ac"),
    ("(?:(a)x|(a)y)", "ay"),
    ("(a)(?:(b)c|bd)", "abd"),
    ("(?:(a)|(a)b)+c", "aabc"),
    ("(?:(a)|ab)+?c", "abc"),
    ("(a)*(?:a(b))?ab", "aab"),
])
def test_backtracking_resets_captures(pat, s):
    check("match", pat, s)


# ---------------------------------------------------------------- 빈 반복 규칙
@pytest.mark.parametrize("pat,s", [
    ("(a|)+", "aa"),
    ("(a?)*", "aa"),
    ("(?:a|())*", "aa"),
    ("(?:()|a)*", "aa"),
    ("(?:(a)|())*", "aa"),
    ("(|a)+b", "aab"),
    ("(|a)*?b", "ab"),
    ("(a*?)+?b", "aab"),
    ("(a*)+", "aa"),
])
def test_empty_iteration_rule(pat, s):
    check("match", pat, s)


# ---------------------------------------------------------------- 역참조
@pytest.mark.parametrize("pat,s,flags", [
    (r"(\w+) \1", "hello hello", ""),
    (r"(a)?b\1", "b", ""),
    (r"(?:(a)|b)\1", "bbaa", ""),
    (r"(a)|b\1", "ba", ""),
    (r"(?P<x>a|b)(?P=x)", "abb", ""),
    (r"(ab)\1", "abAB", "I"),
    (r"(?P<x>é)(?P=x)", "éÉ", "I"),
    (r"(a*)\1$", "aaaa", ""),
    (r"(a)(b)(c)(d)(e)(f)(g)(h)(i)(j)\10", "abcdefghijj", ""),
    (r"(a)\1{2}", "aaaa", ""),
    (r"(?:(a)|b)+\1", "aba", ""),
    (r"\b(\w)(\w)?\w?\2\1\b", "ab abba level", ""),
])
def test_backreferences(pat, s, flags):
    check("search", pat, s, flags)


# ---------------------------------------------------------------- 전방·후방 탐색
@pytest.mark.parametrize("pat,s", [
    ("a(?=b)", "ac ab"),
    ("a(?!b)", "ab ac"),
    (r"(?=(a+))a\1", "aaa"),
    (r"(?=(a|ab))\1c", "abc"),
    (r"(?=(\w+))\w", "ab"),
    (r"(?!(a)b)a(c)", "ac"),
    (r"(?=(a))\1\1", "aab"),
    ("(?<=a)b", "cb ab"),
    ("(?<!a)b", "ab cb"),
    ("(?<=ab|cd)x", "abycdx"),
    ("(?<=(a))b", "ab"),
    (r"(?<=\d{3})x", "12x 123x"),
    ("(?<!x)a", "a"),
    ("(?<=x)a", "a"),
    ("(?<=a)(?=b)", "aab"),
    (r"(?<![\w])\d+", "a1 22"),
    (r"(?<=(a)|(b))c", "bc ac"),
    (r"(a)(?=\1)", "aba aa"),
    (r"(?<=(a))b\1", "aba"),
    (r"(?<=a(?=b))b", "ab"),
    (r"a(?=\n?\Z)", "a\n"),
])
def test_lookaround(pat, s):
    check("search", pat, s)


# ---------------------------------------------------------------- lastindex / lastgroup
@pytest.mark.parametrize("pat,s", [
    ("(a)(b)", "ab"),
    ("((a)b)", "ab"),
    ("((ab))", "ab"),
    ("(a)|b", "b"),
    ("(a)(b)?", "a"),
    ("(?:(a)(b)c|(a)bd)", "abd"),
    ("(a)(?:(b)c|bd)", "abd"),
    ("(?=(a))a", "a"),
    ("(?:(a)|(b))+", "aba"),
    ("(?!(a)b)a", "ac"),
    ("(?P<x>a)(?P<y>b)?", "a"),
    ("(?P<x>a)(b)", "ab"),
    ("(?P<outer>(?P<inner>a))", "a"),
])
def test_lastindex_lastgroup(pat, s):
    rm = re.search(pat, s)
    mm = minire.search(pat, s)
    assert (mm.lastindex, mm.lastgroup) == (rm.lastindex, rm.lastgroup), pat
