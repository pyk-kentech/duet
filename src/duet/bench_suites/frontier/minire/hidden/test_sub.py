"""sub · subn · 치환 템플릿 · 콜러블 repl · count · Match.expand.

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


def outcome(mod, f):
    try:
        return ("ok", f())
    except IndexError:
        return ("IndexError",)
    except mod.error:
        return ("error",)


# ---------------------------------------------------------------- 빈 매치와 sub
@pytest.mark.parametrize("pat,repl,s,count,flags", [
    ("x*", "-", "abxd", 0, ""),
    ("a*", "-", "baac", 0, ""),
    ("", "-", "abc", 0, ""),
    ("b*|a", "-", "aab", 0, ""),
    ("(?<=a)", "-", "aab", 0, ""),
    ("$", "X", "a\n", 0, ""),
    ("$", "X", "a\nb\n", 0, "M"),
    ("^", ">", "a\nb\n", 0, "M"),
    ("A", "x", "aA", 0, "I"),
    ("a", "b", "aaaa", 2, ""),
    ("x*", "-", "abc", 2, ""),
    ("a", "b", "aaa", -1, ""),
    (r"\s+", " ", "a  b \t c", 0, ""),
    ("(?<=,)|(?=,)", " ", "a,b", 0, ""),
    (r"\b", "|", "ab cd", 0, ""),
])
def test_sub_scanning_and_count(pat, repl, s, count, flags):
    got = minire.compile(pat, fl(minire, flags)).sub(repl, s, count=count)
    assert got == re.compile(pat, fl(re, flags)).sub(repl, s, count=count), pat


# ---------------------------------------------------------------- 템플릿
@pytest.mark.parametrize("pat,repl,s", [
    ("(a)(b)?", r"[\2]", "aab"),
    ("a(b)", r"<\g<0>|\g<1>|\1>", "xaby"),
    (r"(?P<w>\w+)", r"<\g<w>>", "hi yo"),
    (r"(a)(b)(c)(d)(e)(f)(g)(h)(i)(j)", r"\10\1", "abcdefghij"),
    ("(a)", r"\g<1>0", "a"),
    ("a", r"\n\t\\", "xay"),
    ("a", r"[\b]", "a"),
    ("a", r"\-\.\é\&", "a"),
    ("(a)|b", r"[\1]", "ab"),
    (r"(\w+)@(\w+)\.com", r"\2 at \1", "joe@site.com, ann@x.com"),
    ("(?P<n>b)", r"\g<n>\g<1>\1", "abc"),
    ("a", "\\", "bbb"),
])
def test_templates(pat, repl, s):
    got = outcome(minire, lambda: minire.compile(pat).sub(repl, s))
    assert got == outcome(re, lambda: re.compile(pat).sub(repl, s)), (pat, repl)


# ---------------------------------------------------------------- 템플릿 오류: 매치가 없어도 낸다
@pytest.mark.parametrize("pat,repl,s,count", [
    ("(a)", r"\2", "a", 0),
    ("x", r"\1", "abc", 0),
    ("(a)", r"\g<2>", "a", 0),
    ("(?P<n>a)", r"\g<m>", "a", 0),
    ("(?P<n>x)", r"\g<m>", "abc", 0),
    ("(a)", r"\g<1", "a", 0),
    ("(a)", r"\g", "a", 0),
    ("(a)", r"\g<>", "a", 0),
    ("(a)", r"\g<-1>", "a", 0),
    ("(a)", r"\q", "a", 0),
    ("(a)", r"x\d", "a", 0),
    ("(a)", r"\10", "a", 0),
    ("(a)", r"\2", "a", -1),
])
def test_template_errors(pat, repl, s, count):
    got = outcome(minire, lambda: minire.compile(pat).sub(repl, s, count=count))
    assert got == outcome(re, lambda: re.compile(pat).sub(repl, s, count=count)), (pat, repl)


# ---------------------------------------------------------------- subn
@pytest.mark.parametrize("pat,repl,s,count", [
    ("x*", "-", "abc", 0),
    ("a", "b", "aaa", 2),
    ("z", "y", "abc", 0),
    ("a", "b", "aaa", -1),
])
def test_subn(pat, repl, s, count):
    assert minire.compile(pat).subn(repl, s, count=count) == re.compile(pat).subn(repl, s, count=count)


# ---------------------------------------------------------------- 콜러블 repl
def test_callable_repl_basic():
    f = lambda m: str(int(m.group()) * 2)  # noqa: E731
    assert minire.sub(r"\d+", f, "a1b22") == re.sub(r"\d+", f, "a1b22")


def test_callable_result_is_inserted_literally():
    f = lambda m: "\\" + m.group() + r"\1\g<0>"  # noqa: E731
    assert minire.sub(r"(\d)", f, "a1b2") == re.sub(r"(\d)", f, "a1b2")


def test_callable_sees_empty_matches_and_groups():
    f = lambda m: repr((m.group(), m.groups(), m.span()))  # noqa: E731
    assert minire.sub(r"(x)?", f, "ab") == re.sub(r"(x)?", f, "ab")


def test_callable_match_pos_endpos_string():
    f = lambda m: "%d,%d,%s" % (m.pos, m.endpos, m.string)  # noqa: E731
    assert minire.sub("b", f, "abcb") == re.sub("b", f, "abcb")


def test_callable_with_count_and_subn():
    f = lambda m: m.group().upper()  # noqa: E731
    assert minire.subn("[a-c]", f, "abcabc", count=4) == re.subn("[a-c]", f, "abcabc", count=4)


# ---------------------------------------------------------------- Match.expand
@pytest.mark.parametrize("pat,s,template", [
    ("(a)(?P<n>b)?", "xa", r"[\1|\g<n>|\g<0>]"),
    (r"(\w+) (\w+)", "hello world", r"\2\n\1\t\\"),
    ("(?P<n>a)", "a", r"\g<n>\-"),
])
def test_expand(pat, s, template):
    assert minire.search(pat, s).expand(template) == re.search(pat, s).expand(template)
