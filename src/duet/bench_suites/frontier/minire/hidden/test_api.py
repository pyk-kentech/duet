"""공개 API: Pattern·Match 속성과 메서드, 모듈 함수, 플래그, escape, 오류, re 를 쓰지 않았는지.

기대값은 대부분 채점 때 파이썬 re 로 계산한다(신탁).
"""

import ast
import importlib.util
import re
from pathlib import Path

import pytest

import minire


# ---------------------------------------------------------------- 플래그와 오류 클래스
def test_flag_values_and_combination():
    assert (minire.IGNORECASE, minire.MULTILINE, minire.DOTALL) == (2, 8, 16)
    assert (minire.I, minire.M, minire.S) == (2, 8, 16)
    p = minire.compile("^a.", minire.I | minire.M | minire.S)
    assert [m.span() for m in p.finditer("xa\nA\n")] == [m.span() for m in re.finditer("^a.", "xa\nA\n", re.I | re.M | re.S)]


def test_error_is_exception_subclass():
    assert issubclass(minire.error, Exception)
    with pytest.raises(minire.error):
        minire.compile("(")


# ---------------------------------------------------------------- Pattern
def test_pattern_attributes():
    pat = r"(?P<x>a)(b)(?:c)(?P<y>d)(?=(e))"
    p = minire.compile(pat)
    rp = re.compile(pat)
    assert p.pattern == pat
    assert p.groups == rp.groups == 4
    assert dict(p.groupindex) == dict(rp.groupindex)


# ---------------------------------------------------------------- Match
def _pair(pat, s, *args):
    return minire.compile(pat).search(s, *args), re.compile(pat).search(s, *args)


def test_match_attributes():
    p = minire.compile("b")
    m = p.search("abcb", 2)
    assert m.re is p and m.string == "abcb" and (m.pos, m.endpos) == (2, 4)
    m2, r2 = _pair("a", "xab", -3, 99)
    assert (m2.pos, m2.endpos) == (r2.pos, r2.endpos)


def test_finditer_matches_report_given_pos_endpos():
    got = [(m.span(), m.pos, m.endpos) for m in minire.compile(r"\w").finditer("abcd", 1, 3)]
    exp = [(m.span(), m.pos, m.endpos) for m in re.compile(r"\w").finditer("abcd", 1, 3)]
    assert got == exp


def test_group_forms():
    m, r = _pair(r"(?P<n>a)(b)?(c)", "xac")
    assert m.group() == r.group() and m.group(0) == r.group(0)
    assert m.group(1, 2, "n", 3) == r.group(1, 2, "n", 3)
    assert (m["n"], m[0], m[2]) == (r["n"], r[0], r[2])


def test_groups_and_groupdict_defaults():
    m, r = _pair(r"(?P<x>a)|(?P<y>b)|(c)", "c")
    assert m.groups() == r.groups()
    assert m.groups("-") == r.groups("-")
    assert m.groupdict() == r.groupdict()
    assert m.groupdict(0) == r.groupdict(0)


def test_start_end_span_unmatched_group_is_minus_one():
    m, r = _pair("(a)|(b)", "b")
    assert (m.start(1), m.end(1), m.span(1)) == (r.start(1), r.end(1), r.span(1))
    assert (m.start(2), m.end(2), m.span(2), m.span()) == (r.start(2), r.end(2), r.span(2), r.span())


def test_start_end_by_name():
    m, r = _pair(r"(?P<w>\w+)!", "hi yo!")
    assert (m.start("w"), m.end("w"), m.span("w")) == (r.start("w"), r.end("w"), r.span("w"))


@pytest.mark.parametrize("call", [
    lambda m: m.group(3),
    lambda m: m.group(-1),
    lambda m: m.group("nope"),
    lambda m: m.start(9),
    lambda m: m.span("nope"),
    lambda m: m[5],
])
def test_bad_group_reference_raises_index_error(call):
    with pytest.raises(IndexError):
        call(re.search("(a)(b)", "ab"))
    with pytest.raises(IndexError):
        call(minire.search("(a)(b)", "ab"))


def test_match_without_groups():
    m, r = _pair("a+", "baa")
    assert (m.groups(), m.groupdict(), m.lastindex, m.lastgroup) == (r.groups(), r.groupdict(), r.lastindex, r.lastgroup)


# ---------------------------------------------------------------- 모듈 함수
def _norm(m):
    return None if m is None else (m.span(), m.groups())


def test_module_match_search_fullmatch():
    for name in ("match", "search", "fullmatch"):
        for pat, s, f in [("a(b)", "ab", 0), ("A(B)", "xab", re.I), ("b$", "a\nb", re.M), ("a.b", "a\nb", re.S)]:
            mf = {0: 0, re.I: minire.I, re.M: minire.M, re.S: minire.S}[f]
            assert _norm(getattr(minire, name)(pat, s, flags=mf)) == _norm(getattr(re, name)(pat, s, flags=f)), (name, pat)


def test_module_findall_finditer():
    assert minire.findall("A", "aAb", flags=minire.I) == re.findall("A", "aAb", flags=re.I)
    assert [m.span() for m in minire.finditer("^.", "a\nb", flags=minire.M)] == \
        [m.span() for m in re.finditer("^.", "a\nb", flags=re.M)]


def test_module_sub_subn_split():
    assert minire.sub("a", "x", "aAa", count=2, flags=minire.I) == re.sub("a", "x", "aAa", count=2, flags=re.I)
    assert minire.subn("a", "x", "aAa", flags=minire.I) == re.subn("a", "x", "aAa", flags=re.I)
    assert minire.split("a", "xAyaz", maxsplit=1, flags=minire.I) == re.split("a", "xAyaz", maxsplit=1, flags=re.I)


# ---------------------------------------------------------------- escape
@pytest.mark.parametrize("s", [
    "a.b*c",
    "()[]{}?*+-|^$\\.&~# \t\n\r\x0b\x0c",
    "_x9!@%=,:;<>\"'/`é東",
])
def test_escape(s):
    assert minire.escape(s) == re.escape(s)
    assert minire.fullmatch(minire.escape(s), s) is not None


# ---------------------------------------------------------------- 잘못된 패턴
@pytest.mark.parametrize("pat", [
    # 잘못된 것
    "(ab", "ab)", "a(b(c)", "*a", "a|*b", "(+a)", "{2}", "^*", r"\b+", "$?",
    "a**", "a{2}*", "a*??", "x{3,2}",
    "[z-a]", r"[\d-z]", "[]", "[^]", "[a", r"[\A]", r"[\q]", r"\q", "a\\",
    r"\1", r"(a)\2", r"(a\1)", r"\2(a)(b)", r"(a)\11",
    "(?P<n>a)(?P=m)", "(?P<n>a)(?P<n>b)", "(?P<1n>a)", "(?P<>a)", "(?P<n>a(?P=n))",
    "(?<=a+)b", "(?<=a|bc)x", "(?<=a{1,2})x",
    # 올바른 것
    "{", "a{,}", "a{1,b}", "[]a]", r"[\d-]", r"[\b]", "(?<=ab|cd)x", "(?<=a{2})b",
    r"(a)\1", "(?P<n>a)(?P=n)", "(?:a*)*", "()|", "",
])
def test_invalid_patterns_raise_error(pat):
    try:
        re.compile(pat)
        expected = "ok"
    except re.error:
        expected = "error"
    try:
        minire.compile(pat)
        got = "ok"
    except minire.error:
        got = "error"
    assert got == expected, pat


# ---------------------------------------------------------------- re 를 쓰지 않았는지
FORBIDDEN = {"re", "sre_compile", "sre_parse", "sre_constants", "_sre", "regex", "fnmatch"}


def _forbidden_uses(tree):
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bad += [a.name for a in node.names if a.name.split(".")[0] in FORBIDDEN]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and node.module.split(".")[0] in FORBIDDEN:
                bad.append(node.module)
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
            if name in ("__import__", "import_module") and node.args:
                a = node.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.split(".")[0] in FORBIDDEN:
                    bad.append(a.value)
        elif isinstance(node, ast.Subscript):
            v, k = node.value, node.slice
            if (isinstance(v, ast.Attribute) and v.attr == "modules" and isinstance(k, ast.Constant)
                    and isinstance(k.value, str) and k.value.split(".")[0] in FORBIDDEN):
                bad.append(k.value)
    return bad


def test_package_does_not_use_re_and_works():
    spec = importlib.util.find_spec("minire")
    assert spec is not None and spec.submodule_search_locations, "minire 는 패키지(폴더)여야 한다"
    root = Path(list(spec.submodule_search_locations)[0])
    files = sorted(root.rglob("*.py"))
    assert files
    bad = {}
    for f in files:
        uses = _forbidden_uses(ast.parse(f.read_bytes(), filename=str(f)))
        if uses:
            bad[str(f.relative_to(root))] = uses
    assert not bad, bad
    # 빈 껍데기가 아니라 실제로 동작해야 한다
    m = minire.compile(r"(a+)(b)?").search("xaab")
    assert m is not None and m.span() == (1, 4) and m.groups() == ("aa", "b")
