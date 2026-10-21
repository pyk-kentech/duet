import pytest

from sheet import Error, FormulaError, Sheet


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


CONSTANTS = [
    ("42", 42), ("-3.5", -3.5), ("+7", 7), ("1e3", 1000), (".5", 0.5), ("5.", 5), ("-.5", -0.5),
    ("1.50", 1.5), ("2E-2", 0.02),
    ("true", True), ("FALSE", False), ("True", True),
    ("abc", "abc"), (" 42", " 42"), ("1,000", "1,000"), ("1e", "1e"), ("--1", "--1"), ("TRUE ", "TRUE "),
    ("'123", "123"), ("'", ""), ("''x", "'x"), ("#DIV/0!", "#DIV/0!"), ("'=1+2", "=1+2"),
]


@pytest.mark.parametrize("text,want", CONSTANTS)
def test_constant_values_and_text(text, want):
    s = Sheet()
    s.set("B2", text)
    check(s.get("B2"), want)
    assert s.formula("B2") == text


TYPES = [
    ("1.0", int, 1), ("2.5", float, 2.5), ("=10/4", float, 2.5), ("=10/5", int, 2), ("=-0", int, 0),
    ("=0.5*4", int, 2), ("1e3", int, 1000), ("=ROUND(2.5,0)", int, 3), ('=LEN("ab")', int, 2),
    ("=AVERAGE(1,2)", float, 1.5),
]


@pytest.mark.parametrize("text,typ,want", TYPES)
def test_integral_numbers_are_int(text, typ, want):
    s = Sheet()
    s.set("C3", text)
    v = s.get("C3")
    assert type(v) is typ and v == want, v


def test_empty_cells():
    s = Sheet()
    assert s.get("A1") is None and s.formula("A1") == ""
    s.set("A1", "5")
    s.set("A1", "")
    assert s.get("A1") is None and s.formula("A1") == ""
    s.set("Q7", "")      # 빈 셀을 비워도 괜찮다
    assert s.get("Q7") is None


def test_bad_addresses_raise_value_error():
    s = Sheet()
    for ref in ["A0", "A01", "$A$1", "XFE1", "A1048577", "1A", "", "A", "AAAA1", "A1:B2", "A 1"]:
        with pytest.raises(ValueError):
            s.get(ref)
        with pytest.raises(ValueError):
            s.set(ref, "1")


def test_good_addresses():
    s = Sheet()
    s.set("xfd1048576", "7")
    assert s.get("XFD1048576") == 7
    s.set("aa10", "x")
    assert s.get("AA10") == "x" and s.formula("aA10") == "x"


def test_error_type():
    a, b = Error("#N/A"), Error("#N/A")
    assert a == b and hash(a) == hash(b) and a.code == "#N/A" and str(a) == "#N/A"
    assert a != Error("#REF!")
    assert not isinstance(a, str) and a != "#N/A"
    assert issubclass(FormulaError, ValueError)


def test_formula_error_leaves_cell_unchanged():
    s = Sheet()
    s.set("A1", "5")
    with pytest.raises(FormulaError):
        s.set("A1", "=1+")
    assert s.get("A1") == 5 and s.formula("A1") == "5"
    s.set("B1", "=A1*2")
    with pytest.raises(FormulaError):
        s.set("B1", "=(")
    assert s.get("B1") == 10 and s.formula("B1") == "=A1*2"
    with pytest.raises(FormulaError):
        s.set("C1", "=SUM()")
    assert s.get("C1") is None and s.formula("C1") == ""
