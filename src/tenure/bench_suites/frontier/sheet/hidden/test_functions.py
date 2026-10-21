import pytest

from sheet import Error, Sheet

DIV0, VALUE, REF, NAME = Error("#DIV/0!"), Error("#VALUE!"), Error("#REF!"), Error("#NAME?")

# A4, C3, K3 은 비어 있다.
BASE = {
    "A1": "1", "A2": "TRUE", "A3": "'5", "A5": "x", "A6": "2.5",
    "B1": "=1/0", "B2": '="a"+1',
    "C1": "TRUE", "C2": "x", "C4": "0", "C5": "2",
    "D1": "1", "E1": "=1/0", "D2": '=-"x"', "E2": "2",
    "G1": "a", "H1": "b", "G2": "c", "H2": "d",
    "K1": "'", "K2": '=""',
}


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


SUM = [
    ("=SUM(A1:A6)", 3.5), ('=SUM(TRUE,"2")', 3), ("=SUM(A2)", 0), ("=SUM(A3)", 0), ("=SUM(A3+0)", 5),
    ('=SUM("x")', VALUE), ("=SUM(A5)", 0), ("=SUM((A1:A6))", 3.5), ("=SUM(A1:A6,10)", 13.5),
    ("=SUM(0.1,0.2,0.3)", 0.6000000000000001), ("=SUM(A4)", 0), ("=SUM(D1:E2)", DIV0), ("=SUM(1/0,B2)", DIV0),
    ('=SUM("x",1/0)', VALUE), ("=SUM(B2,B1)", VALUE), ("=SUM(-A2)", -1), ("=sum(a1,a6)", 3.5),
]


@pytest.mark.parametrize("formula,want", SUM)
def test_sum(formula, want):
    check(ev(formula), want)


AGGREGATES = [
    ("=AVERAGE(A1:A6)", 1.75), ("=AVERAGE(A3:A5)", DIV0), ("=AVERAGE(TRUE,3)", 2),
    ("=AVERAGE(1,2,4)", 2.3333333333333335), ("=AVERAGE(A1,B2)", VALUE),
    ("=MIN(A2:A5)", 0), ("=MAX(-5,A4)", -5), ('=MAX("3",2)', 3), ("=MIN(TRUE,5)", 1), ("=MAX(A1:A6)", 2.5),
    ("=MIN(A1:A6,-1)", -1), ("=MIN(D1:E2)", DIV0),
    ("=COUNT(A1:A6)", 2), ('=COUNT("3",TRUE,"x",1/0)', 2), ("=COUNT(A1:B2)", 1), ("=COUNT(A3)", 0),
    ("=COUNT(A3+0)", 1), ("=COUNT(D1:E2)", 2),
    ("=COUNTA(A1:A6)", 5), ("=COUNTA(B1:B2)", 2), ('=COUNTA(1/0,"")', 2), ("=COUNTA(K1:K3)", 2), ("=COUNTA(A4)", 0),
]


@pytest.mark.parametrize("formula,want", AGGREGATES)
def test_average_min_max_count(formula, want):
    check(ev(formula), want)


LOGIC = [
    ("=AND(C1:C3)", True), ("=AND(C1:C4)", False), ("=OR(C4:C5)", True), ("=AND(C2:C3)", VALUE),
    ('=AND("TRUE")', VALUE), ("=AND(FALSE,1/0)", DIV0), ("=OR(TRUE,1/0)", DIV0), ("=OR(0,FALSE)", False),
    ("=AND(1,TRUE)", True), ("=OR(C2)", VALUE), ("=OR(C1:C5,B2)", VALUE), ("=AND(C3)", VALUE),
    ("=NOT(0)", True), ('=NOT("a")', VALUE), ("=NOT(C3)", True), ("=NOT(C5)", False), ("=NOT(B2)", VALUE),
]


@pytest.mark.parametrize("formula,want", LOGIC)
def test_and_or_not(formula, want):
    check(ev(formula), want)


IFS = [
    ('=IF(1,"y","n")', "y"), ('=IF(0,"y","n")', "n"), ('=IF("TRUE",1,2)', VALUE), ("=IF(C3,1,2)", 2),
    ("=IF(FALSE,1)", False), ("=IF(TRUE,1/0,2)", DIV0), ("=IF(FALSE,1/0,2)", 2), ("=IF(1/0,1,2)", DIV0),
    ("=IF(TRUE,C3)", 0), ('=IF(TRUE,C3)&"x"', "0x"), ("=IF(C1:C2,1,2)", VALUE), ("=IF(TRUE,C1:C2)", VALUE),
    ("=IF(C5,C2)", "x"), ("=IF(A3,1,2)", VALUE),
    ('=IFERROR(1/0,"x")', "x"), ("=IFERROR(5,1/0)", 5), ("=IFERROR(C3,1)", 0), ("=IFERROR(#N/A,2)", 2),
    ("=IFERROR(1/0,#REF!)", REF), ("=IFERROR(#N/A,B1)", DIV0), ("=IFERROR(C1:C2,7)", 7), ("=IFERROR(B1,C3)", 0),
]


@pytest.mark.parametrize("formula,want", IFS)
def test_if_and_iferror(formula, want):
    check(ev(formula), want)


ROUND = [
    ("=ROUND(2.5,0)", 3), ("=ROUND(-2.5,0)", -3), ("=ROUND(2.675,2)", 2.68), ("=ROUND(1.005,2)", 1.01),
    ("=ROUND(1250,-2)", 1300), ("=ROUND(-1250,-2)", -1300), ("=ROUND(1234.567,-2)", 1200),
    ("=ROUND(12.3456,2.9)", 12.35), ("=ROUND(12.5,-0.9)", 13), ('=ROUND("2.5",0)', 3), ("=ROUND(C3,0)", 0),
    ("=ROUND(0.125,2)", 0.13), ("=ROUND(-0.4,0)", 0), ("=ROUND(1/0,B2)", DIV0), ('=ROUND(2,"x")', VALUE),
    ("=ROUND(-1.55,1)", -1.6),
    ("=ABS(-3)", 3), ('=ABS("-2.5")', 2.5), ('=ABS("x")', VALUE), ("=ABS(C1)", 1), ("=ABS(C1:C2)", VALUE),
]


@pytest.mark.parametrize("formula,want", ROUND)
def test_round_and_abs(formula, want):
    check(ev(formula), want)


TEXT = [
    ("=CONCAT(A1:A6)", "1TRUE5x2.5"), ('=CONCAT("a",1.50,TRUE)', "a1.5TRUE"), ("=CONCAT(B1:B2)", DIV0),
    ("=CONCAT(G1:H2)", "abcd"), ('=CONCAT(A4,"z")', "z"),
    ("=LEN(0.5)", 3), ("=LEN(TRUE)", 4), ("=LEN(C3)", 0), ('=LEN("héllo")', 5), ("=LEN(1E3)", 4),
    ("=LEN(1/0)", DIV0), ("=LEN(A6)", 3), ("=LEN(G1:H1)", VALUE),
    ('=UPPER("abc")', "ABC"), ("=UPPER(TRUE)", "TRUE"), ("=UPPER(1.5)", "1.5"), ("=UPPER(A5)", "X"),
    ("=FOO(1)", NAME), ("=NOPE(A1:A2)", NAME),
]


@pytest.mark.parametrize("formula,want", TEXT)
def test_text_functions(formula, want):
    check(ev(formula), want)
