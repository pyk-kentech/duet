import pytest

from sheet import Error, FormulaError, Sheet

NAME, NUM, DIV0 = Error("#NAME?"), Error("#NUM!"), Error("#DIV/0!")


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


def ev(formula, **cells):
    s = Sheet()
    for k, v in cells.items():
        s.set(k, v)
    s.set("ZZ999", formula)
    return s.get("ZZ999")


NORMALIZE = [
    ("= sum( a1 , b2:a1 )*2", "=SUM(A1,A1:B2)*2"),
    ("=1 + 2", "=1+2"),
    ('="a  B"&" c"', '="a  B"&" c"'),
    ('="say ""hi"""', '="say ""hi"""'),
    ("=1.50e2+.5", "=1.50E2+.5"),
    ("=sum($b$3:a1)", "=SUM(A1:$B$3)"),
    ("=SUM(B$1:$A3)", "=SUM($A$1:B3)"),
    ("=SUM(A2:$A1)", "=SUM(A1:$A2)"),
    ("=if(true,#n/a,foo)", "=IF(TRUE,#N/A,FOO)"),
    ("=((1))", "=((1))"),
    ("=-+-1", "=-+-1"),
    ("=10 % %", "=10%%"),
    ("=a1 <> b1", "=A1<>B1"),
    ("=Aa10*xfd1048576", "=AA10*XFD1048576"),
    ("=myFunc( 1 , 2 )", "=MYFUNC(1,2)"),
    ("=\t1\n+\r2", "=1+2"),
]


@pytest.mark.parametrize("text,want", NORMALIZE)
def test_normalized_formula_text(text, want):
    s = Sheet()
    s.set("ZZ999", text)
    assert s.formula("ZZ999") == want


PRECEDENCE = [
    ("=-2^2", 4), ("=0-2^2", -4), ("=2^3^2", 64), ("=2^-1", 0.5), ("=-2^-2", 0.25),
    ("=2+3*4", 14), ("=(2+3)*4", 20), ("=10-4-3", 3), ("=48/4/3", 4), ("=3*2^2", 12), ("=2-3^2", -7),
    ("=50%", 0.5), ("=10%%", 0.001), ("=-50%", -0.5), ("=200%*3", 6), ("=2^200%", 4), ("=-2%^2", 0.0004),
    ("=1+2&3", "33"), ('="a"&1+2', "a3"), ("=1&2=12", False), ('=1&2="12"', True), ("=2&3^2", "29"),
    ("=1<2<3", False), ("=3>2>1", True), ("=1+2=3", True),
    ("=-8^(1/3)", NUM), ("=0-8^(1/3)", -2), ("=--2", 2),
]


@pytest.mark.parametrize("formula,want", PRECEDENCE)
def test_precedence_and_associativity(formula, want):
    check(ev(formula), want)


SYNTAX_ERRORS = [
    "=", "=1+", "=(1", "=1)", "=SUM()", "=IF(1)", "=ROUND(1)", '="abc', "=A1:", "=1 2", "=SUM(1,,2)",
    "=SUM(1,)", "=A1:1", "=#FOO!", "=A$0", "=1+*2", "=NOT(1,2)", "=COUNTIF(A1:A2)", "=@A1", "=A1:B2:C3",
    "=SUM (1)", "=$A",
]


@pytest.mark.parametrize("text", SYNTAX_ERRORS)
def test_syntax_errors(text):
    s = Sheet()
    with pytest.raises(FormulaError):
        s.set("B2", text)
    assert s.get("B2") is None


NAMES = [
    ("=foo", NAME), ("=A0", NAME), ("=XFE1", NAME), ("=AAAA1", NAME), ("=A1B", NAME), ("=_x1", NAME),
    ("=foo(1/0)", NAME), ("=FOO()+1/0", NAME), ("=1/0+FOO()", DIV0), ("=IF(TRUE,1,FOO)", 1),
    ("=true", True), ("=False", False), ("=1e3", 1000),
]


@pytest.mark.parametrize("formula,want", NAMES)
def test_names_and_literals(formula, want):
    check(ev(formula), want)


def test_name_formula_text_and_far_reference():
    s = Sheet()
    s.set("A1", "=a0+xfe1")
    assert s.formula("A1") == "=A0+XFE1" and s.get("A1") == NAME
    s.set("XFD1", "7")
    s.set("B1", "=xfd1*2")
    assert s.get("B1") == 14 and s.formula("B1") == "=XFD1*2"
