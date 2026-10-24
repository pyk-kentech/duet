"""앵커(^ $ \\A \\Z \\b \\B), MULTILINE, pos·endpos.

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


def run(p, op, s, args, n):
    if op == "iter":
        return [m.span() for m in p.finditer(s, *args)]
    if op == "findall":
        return p.findall(s, *args)
    return spans(getattr(p, op)(s, *args), n)


def check(op, pat, s, flags="", args=()):
    rp = re.compile(pat, fl(re, flags))
    mp = minire.compile(pat, fl(minire, flags))
    n = rp.groups
    assert run(mp, op, s, args, n) == run(rp, op, s, args, n), (op, pat, s, flags, args)


# ---------------------------------------------------------------- ^ $ \A \Z 와 MULTILINE
@pytest.mark.parametrize("op,pat,s,flags", [
    ("search", "^a", "ba", ""),
    ("search", "^a", "b\na", "M"),
    ("search", "a$", "a\n", ""),
    ("search", "a$", "a\n\n", ""),
    ("search", r"a\Z", "a\n", ""),
    ("iter", "$", "a\n", ""),
    ("iter", "$", "\n\n", ""),
    ("iter", "$", "\n\n", "M"),
    ("iter", "^", "a\nb\n", "M"),
    ("iter", "$", "a\nb\n", "M"),
    ("iter", "^$", "a\n\nb", "M"),
    ("search", r"\Aa", "b\na", "M"),
    ("search", r"a\Z", "a\nb", "M"),
    ("findall", "^.+$", "a\nb", "M"),
    ("findall", "^.+$", "a\nb", "MS"),
    ("findall", ".$", "ab\ncd\n", "M"),
    ("findall", ".$", "ab\ncd\n", ""),
    ("search", r"\A\Z", "", ""),
    ("search", "^$", "\n", ""),
    ("findall", r"(?:^a\n?)+", "a\na\nb", "M"),
])
def test_line_anchors(op, pat, s, flags):
    check(op, pat, s, flags)


# ---------------------------------------------------------------- 단어 경계
@pytest.mark.parametrize("op,pat,s", [
    ("iter", r"\b", "ab cd"),
    ("iter", r"\b", "a_b-c"),
    ("iter", r"\B", "ab c"),
    ("search", r"\Ba\B", "a bab"),
    ("search", r"\bé", "aé é"),
    ("findall", r"\b\w", "hi, you-there"),
    ("search", r"\b", ""),
    ("findall", r"\w+\b", "x1 y2_"),
])
def test_word_boundaries(op, pat, s):
    check(op, pat, s)


# ---------------------------------------------------------------- pos 와 endpos
@pytest.mark.parametrize("op,pat,s,args,flags", [
    ("match", "b", "ab", (1,), ""),
    ("match", "^b", "ab", (1,), ""),
    ("search", "^b", "ab", (1,), ""),
    ("search", r"\Ab", "ab", (1,), ""),
    ("search", "^b", "a\nb", (1,), "M"),
    ("search", "^", "ab", (1,), "M"),
    ("search", "a$", "ab", (0, 1), ""),
    ("search", r"a\Z", "ab", (0, 1), ""),
    ("search", "$", "a\nb", (0, 2), ""),
    ("search", "a(?=b)", "ab", (0, 1), ""),
    ("search", r"\bb", "ab", (1,), ""),
    ("search", r"\Bb", "ab", (1,), ""),
    ("search", r"a\b", "ab", (0, 1), ""),
    ("search", "(?<=a)b", "ab", (1,), ""),
    ("search", "(?<!a)b", "ab", (1,), ""),
    ("search", "a", "ba", (-5,), ""),
    ("search", "b", "ba", (-1,), ""),
    ("search", "a", "ab", (0, -1), ""),
    ("search", "", "abc", (2, 1), ""),
    ("match", "a*", "aaa", (1, 2), ""),
    ("findall", "x*", "abc", (2, 1), ""),
    ("search", "x*", "aaa", (5,), ""),
    ("search", "x*", "aaa", (0, -1), ""),
    ("fullmatch", "a+", "baaab", (1, 4), ""),
    ("fullmatch", "a+", "baaab", (1,), ""),
    ("fullmatch", "a|ab", "xab", (1,), ""),
    ("findall", r"\w+", "ab cd ef", (1, 7), ""),
    ("iter", "x*", "abc", (1, 2), ""),
    ("iter", r"\b", "ab cd", (1, 4), ""),
])
def test_pos_endpos(op, pat, s, args, flags):
    check(op, pat, s, flags, args)
