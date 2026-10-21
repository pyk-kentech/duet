import pytest

from sheet import Error, Sheet

DIV0, VALUE, REF, NA, NUM = Error("#DIV/0!"), Error("#VALUE!"), Error("#REF!"), Error("#N/A"), Error("#NUM!")

# A5, A9 는 비어 있다. A1 은 글자 "3", A2 는 글자 " 4 ", A6 은 빈 글자.
BASE = {"A1": "'3", "A2": " 4 ", "A3": "abc", "A4": "TRUE", "A6": "'", "A7": "=1/0", "A8": "1.50"}


def check(got, want):
    if want is None:
        assert got is None
    elif isinstance(want, bool):
        assert got is want, got
    elif isinstance(want, Error):
        assert isinstance(got, Error) and got == want, got
    elif isinstance(want, str):
        assert type(got) is str and got == want, got
    else:
        assert type(got) in (int, float) and got == want, got


def ev(formula):
    s = Sheet()
    for k, v in BASE.items():
        s.set(k, v)
    s.set("ZZ999", formula)
    return s.get("ZZ999")


COERCE = [
    ("=A1+1", 4), ("=A2*2", 8), ("=A3+1", VALUE), ("=A4+A4", 2), ("=A5+1", 1), ("=A6+1", VALUE),
    ('="1e2"+0', 100), ('="TRUE"+0', VALUE), ('="50%"+0', VALUE), ('="1,000"+0', VALUE), ('=" -2.5 "*2', -5),
    ('=-"3"', -3), ("=-A3", VALUE), ("=-A4", -1), ("=A4*5", 5), ("=FALSE+0", 0),
    ("=A1%", 0.03), ('="50"%', 0.5),
]


@pytest.mark.parametrize("formula,want", COERCE)
def test_arithmetic_coercion(formula, want):
    check(ev(formula), want)


UNARY_PLUS = [
    ('=+"a"', "a"), ("=+A4", True), ("=+A5", 0), ('=+"3"+1', 4), ("=+A3", "abc"), ("=+A7", DIV0), ("=+A1:A2", VALUE),
]


@pytest.mark.parametrize("formula,want", UNARY_PLUS)
def test_unary_plus_keeps_value(formula, want):
    check(ev(formula), want)


EMPTY = [
    ("=A5", 0), ('=A5&"x"', "x"), ("=A5=0", True), ('=A5=""', True), ("=A5=FALSE", True), ("=A5<1", True),
    ('=A5<"a"', True), ("=A5=A9", True), ("=LEN(A5)", 0), ("=(A5)", 0), ('=(A5)&"x"', "x"), ("=A5>-1", True),
    ("=A6=0", False), ('=A6=""', True), ("=A6=A5", True), ("=A6", ""),
]


@pytest.mark.parametrize("formula,want", EMPTY)
def test_empty_and_empty_text(formula, want):
    check(ev(formula), want)


COMPARE = [
    ('=1<"a"', True), ('="z"<FALSE', True), ('=1="1"', False), ("=TRUE=1", False), ("=TRUE>100", True),
    ('="abc"="ABC"', True), ('="a"<"B"', True), ('="_"<"a"', True), ("=0.1+0.2=0.3", False), ('="10"<"9"', True),
    ("=FALSE<TRUE", True), ("=A1=3", False), ('=A1="3"', True), ("=A8=1.5", True), ('="b"<>"B"', False),
    ("=-1<FALSE", True),
]


@pytest.mark.parametrize("formula,want", COMPARE)
def test_comparison(formula, want):
    check(ev(formula), want)


ERRORS = [
    ("=1/0", DIV0), ("=0/0", DIV0), ("=1/A5", DIV0), ('="a"+1/0', VALUE), ('=1/0+"a"', DIV0), ('="a"&1/0', DIV0),
    ("=#N/A+#REF!", NA), ("=#N/A=1/0", NA), ("=1/0=#N/A", DIV0), ("=A7*0", DIV0), ('="a"/0', VALUE),
    ('=1/"x"', VALUE), ('=A3*(1/0)', VALUE), ("=(1/0)*A3", DIV0), ('=A7&"x"', DIV0),
    ("=0^0", NUM), ("=0^-1", DIV0), ("=0^0.5", 0), ("=(-8)^(1/3)", NUM), ("=(-8)^3", -512), ("=(-2)^-1", -0.5),
    ("=10^400", NUM), ("=1E308*10", NUM), ("=#NUM!", NUM), ("=#ref!", REF),
    ("=A1:A2", VALUE), ("=A1:A2+1", VALUE), ("=-A1:A2", VALUE),
]


@pytest.mark.parametrize("formula,want", ERRORS)
def test_errors_and_order(formula, want):
    check(ev(formula), want)


FORMAT = [
    ('=1/4&""', "0.25"), ('=0.1*3&""', "0.30000000000000004"), ('=1E3&""', "1000"), ('=1/10000000&""', "1e-07"),
    ('=1.5E20&""', "150000000000000000000"), ("=TRUE&FALSE", "TRUEFALSE"), ('=-0&""', "0"), ('=A8&""', "1.5"),
    ('=1/3&""', "0.3333333333333333"), ('=2^0.5&""', "1.4142135623730951"),
]


@pytest.mark.parametrize("formula,want", FORMAT)
def test_number_to_text(formula, want):
    check(ev(formula), want)
