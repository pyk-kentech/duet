"""문법: 리터럴·escape·중괄호·문자 클래스·점·수량자·대안·유니코드·대소문자 무시.

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
    if op == "findall":
        assert mp.findall(s) == rp.findall(s), (pat, s)
    else:
        n = rp.groups
        assert spans(getattr(mp, op)(s), n) == spans(getattr(rp, op)(s), n), (op, pat, s, flags)


# ---------------------------------------------------------------- 리터럴과 escape
@pytest.mark.parametrize("pat,s", [
    ("abc", "xxabcx"),
    (r"a\.c", "abc a.c"),
    (r"\(\)\[\]\{\}\*\+\?\|\^\$\\", "x()[]{}*+?|^$\\y"),
    (r"a\-b\ c\#\&\~", "a-b c#&~"),
    (r"\n\t\r\f\v", "x\n\t\r\f\vy"),
    ("a]b}c", "a]b}c"),
    ("é+", "aééb"),
])
def test_literals_and_escapes(pat, s):
    check("search", pat, s)


# ---------------------------------------------------------------- 중괄호: 수량자이거나 글자 그대로
@pytest.mark.parametrize("pat,s", [
    ("a{2}", "aaa"),
    ("a{,2}b", "aaab"),
    ("a{2,}", "aaaaa"),
    ("a{,}b", "aaab"),
    ("a{}", "aa{}"),
    ("a{x}", "a{x}"),
    ("a{1,b}", "aa{1,b}"),
    ("a{1", "aa{1"),
    ("x{ 2}", "x{ 2}"),
    ("{", "a{b"),
    ("a{0}b", "ab"),
    ("x{2}{", "xxx{"),
    ("a{1,2}?", "aaa"),
    ("a{2,3}?a", "aaaa"),
    ("[0-9]{2,3}?x", "1234x"),
    ("(ab){2}", "abababx"),
])
def test_braces(pat, s):
    check("search", pat, s)


# ---------------------------------------------------------------- 문자 클래스
@pytest.mark.parametrize("pat,s", [
    ("[^abc]", "abxc\n"),
    ("[]a]", "]ab"),
    ("[^]a]", "]ab"),
    ("[a-]", "a-b"),
    ("[-a]", "a-b"),
    ("[a^]", "^ab"),
    (r"[\]]", "a]"),
    (r"[^\W\d]", "a1_ é"),
    (r"[\b]", "a\x08b"),
    (r"[\n-\r]", "\n\x0b\x0c\r "),
    (r"[a-c-e]", "abcde-"),
    (r"[\d-]", "1-z"),
    (r"[.*+?(){}|$]", ".a*+?(){}|$b"),
    (r"[\\]", "a\\b"),
    (r"[\w-]+", "foo-bar baz_1"),
    (r"[\^\-\]]", "^-]a"),
    (r"[\D\s]", "1 a\t"),
])
def test_char_classes(pat, s):
    check("findall", pat, s)


# ---------------------------------------------------------------- 점과 DOTALL
@pytest.mark.parametrize("op,pat,s,flags", [
    ("findall", ".", "a\nb\r", ""),
    ("findall", ".", "a\nb\r", "S"),
    ("search", "a.c", "a\nc abc", ""),
    ("search", "a.c", "a\nc", "S"),
    ("findall", ".+", "ab\ncd", ""),
])
def test_dot(op, pat, s, flags):
    check(op, pat, s, flags)


# ---------------------------------------------------------------- 수량자와 역추적
@pytest.mark.parametrize("pat,s", [
    ("a*?", "aaa"),
    ("a??b", "ab"),
    ("<.*>", "<a><b>"),
    ("<.*?>", "<a><b>"),
    ("(a+)(a+)", "aaaa"),
    ("(a+?)(a+)", "aaaa"),
    ("(a|ab)(c|bcd)(d*)", "abcd"),
    ("(a|ab)*c", "abac"),
    ("(a|ab)*?c", "ababc"),
    ("(?:a|b)*?b", "aab"),
    (r"(\d+)(\d{2})", "12345"),
    (r"(.*?)(\d+)", "abc123"),
    (r'"((?:[^"\\]|\\.)*)"', r'x "a\"b" y'),
    ("(a{2})*", "aaaaa"),
    ("(?:a{2})+?$", "aaaa"),
])
def test_quantifiers_backtracking(pat, s):
    check("search", pat, s)


# ---------------------------------------------------------------- 대안: 왼쪽 우선(가장 긴 것이 아님)
@pytest.mark.parametrize("pat,s", [
    ("a|ab", "ab"),
    ("(a|ab)(b?)", "ab"),
    ("|a", "a"),
    ("a|", "b"),
    ("cat|category", "category"),
    ("(c|ca|cat)(ts|s)", "cats"),
])
def test_alternation_leftmost_first(pat, s):
    check("search", pat, s)


# ---------------------------------------------------------------- fullmatch 는 끝까지 맞도록 역추적
@pytest.mark.parametrize("pat,s", [
    ("a|ab", "ab"),
    ("(a|ab)(c|bcd)", "abcd"),
    ("a*?", "aaa"),
    ("(a+?)(b*?)", "aab"),
    ("a|b", "ab"),
    ("(?:ab|a)(?:bc|c)", "abc"),
    ("a{2,3}?", "aaa"),
    (r"(\w+?)(\d*)", "ab12"),
    ("a(?=$)", "a"),
    ("a(?=b)", "a"),
])
def test_fullmatch_backtracks(pat, s):
    check("fullmatch", pat, s)


# ---------------------------------------------------------------- 유니코드 정의
@pytest.mark.parametrize("pat,s", [
    (r"\d", "1²٣½"),
    (r"\w", "1²٣½_-é"),
    (r"\s", " \t\n\x0b\x0c\r\x1c\xa0\N{EM SPACE}a"),
    (r"\W+", "a-b é!?c"),
    (r"\b\w+\b", "naïve café, 東京"),
    (r"[^\d\s]+", "ab 12 ٣c"),
    (r"\d+|\W", "²٣4½"),
])
def test_unicode_classes(pat, s):
    check("findall", pat, s)


# ---------------------------------------------------------------- 대소문자 무시
@pytest.mark.parametrize("op,pat,s", [
    ("search", "abc", "xAbC"),
    ("search", "[a-c]+", "xABCD"),
    ("findall", "[^a-c]", "Ab1"),
    ("findall", "[Z-a]", "zZaA_[yB"),
    ("findall", "é|ж+", "ÉЖжЖ"),
    ("search", "[^x]", "X"),
    ("search", r"A[b-d]E\w", "xaCe_"),
])
def test_ignorecase(op, pat, s):
    check(op, pat, s, "I")
