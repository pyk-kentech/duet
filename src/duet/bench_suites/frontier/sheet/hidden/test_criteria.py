import pytest

from sheet import Error, Sheet

DIV0, VALUE, REF = Error("#DIV/0!"), Error("#VALUE!"), Error("#REF!")

# A5, C1 은 비어 있다. A2 는 글자 "5", A7 은 오류.
DATA = {
    "A1": "5", "A2": "'5", "A3": "apple", "A4": "Apple pie", "A6": "TRUE", "A7": "=1/0", "A8": "10",
    "B1": "1", "B2": "2", "B3": "4", "B4": "8", "B5": "16", "B6": "32", "B7": "64", "B8": "128",
    "D1": "a*b", "D2": "axb", "D3": "a?b", "D4": "a~b",
}


def check(got, want):
    if isinstance(want, Error):
        assert isinstance(got, Error) and got == want, got
    else:
        assert type(got) in (int, float) and got == want, got


def ev(formula):
    s = Sheet()
    for k, v in DATA.items():
        s.set(k, v)
    s.set("ZZ999", formula)
    return s.get("ZZ999")


COUNTIF = [
    ("=COUNTIF(A1:A8,5)", 1), ('=COUNTIF(A1:A8,"5")', 1), ('=COUNTIF(A1:A8,"=5")', 1), ('=COUNTIF(A1:A8,">=5")', 2),
    ('=COUNTIF(A1:A8,"<>5")', 6), ('=COUNTIF(A1:A8,"<20")', 2), ('=COUNTIF(A1:A8,">="&A8)', 1),
    ('=COUNTIF(A1:A8,"apple")', 1), ('=COUNTIF(A1:A8,"APPLE*")', 2), ('=COUNTIF(A1:A8,"a?ple")', 1),
    ('=COUNTIF(A1:A8,"*")', 3), ('=COUNTIF(A1:A8,"<>apple")', 6),
    ('=COUNTIF(A1:A8,"")', 1), ('=COUNTIF(A1:A8,"=")', 1), ('=COUNTIF(A1:A8,"<>")', 6), ("=COUNTIF(A1:A8,C1)", 1),
    ("=COUNTIF(A1:A8,TRUE)", 1), ('=COUNTIF(A1:A8,"true")', 1),
    ('=COUNTIF(A1:A8,"<b")', 3), ('=COUNTIF(A1:A8,">a")', 2),
    ("=COUNTIF(A1:A8,1/0)", DIV0), ('=COUNTIF(1,">0")', VALUE), ("=COUNTIF(#REF!,1)", REF),
    ('=COUNTIF(D1:D4,"a~*b")', 1), ('=COUNTIF(D1:D4,"a*b")', 4), ('=COUNTIF(D1:D4,"a?b")', 4),
    ('=COUNTIF(D1:D4,"a~?b")', 1), ('=COUNTIF(D1:D4,"a~b")', 1),
    ('=COUNTIF(A1:A1000,"")', 993),
]


@pytest.mark.parametrize("formula,want", COUNTIF)
def test_countif(formula, want):
    check(ev(formula), want)


SUMIF = [
    ('=SUMIF(A1:A8,">0",B1:B8)', 129), ('=SUMIF(A1:A8,"apple*",B1)', 12), ('=SUMIF(A1:A8,"<>5",B1:B8)', 190),
    ('=SUMIF(B1:B8,">10")', 240), ('=SUMIF(B1:B8,">0",A1:A8)', DIV0), ('=SUMIF(B1:B4,">0",A1)', 5),
    ('=SUMIF(A1:A8,"",B1:B8)', 16), ('=SUMIF(A1:A8,"x",B1:B8)', 0), ('=SUMIF(A1:A8,">0",B1:B2)', 129),
    ('=SUMIF(A1:A8,5,1)', VALUE), ('=SUMIF(A3:A4,"apple*",B5)', 48),
]


@pytest.mark.parametrize("formula,want", SUMIF)
def test_sumif(formula, want):
    check(ev(formula), want)
