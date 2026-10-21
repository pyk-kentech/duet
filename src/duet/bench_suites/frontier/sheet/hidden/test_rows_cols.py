import pytest

from sheet import Error, Sheet

REF = Error("#REF!")


def sheet(**cells):
    s = Sheet()
    for k, v in cells.items():
        s.set(k, v)
    return s


# 수식은 H20 에 둔다. (수식, 연산, 인수, 연산 뒤 수식 셀 위치, 기대 수식)
ROW_CASES = [
    ("=A5", "insert_rows", (5,), "H21", "=A6"),
    ("=A5", "insert_rows", (6,), "H21", "=A5"),
    ("=A5", "insert_rows", (1, 3), "H23", "=A8"),
    ("=$A$5+A$5+$A5", "insert_rows", (2, 2), "H22", "=$A$7+A$7+$A7"),
    ("=SUM(A2:A5)", "insert_rows", (3, 2), "H22", "=SUM(A2:A7)"),
    ("=SUM(A2:A5)", "insert_rows", (2,), "H21", "=SUM(A3:A6)"),
    ("=SUM(A2:A5)", "insert_rows", (5,), "H21", "=SUM(A2:A6)"),
    ("=SUM(A2:A5)", "insert_rows", (6,), "H21", "=SUM(A2:A5)"),
    ("=A5", "delete_rows", (5,), "H19", "=#REF!"),
    ("=A5", "delete_rows", (2, 2), "H18", "=A3"),
    ("=A5+A6", "delete_rows", (5,), "H19", "=#REF!+A5"),
    ("=SUM(A2:A6)", "delete_rows", (3,), "H19", "=SUM(A2:A5)"),
    ("=SUM(A2:A6)", "delete_rows", (1, 2), "H18", "=SUM(A1:A4)"),
    ("=SUM(A2:A6)", "delete_rows", (5, 3), "H17", "=SUM(A2:A4)"),
    ("=SUM(A2:A6)", "delete_rows", (2, 5), "H15", "=SUM(#REF!)"),
    ("=SUM(A2:A6)", "delete_rows", (1, 10), "H10", "=SUM(#REF!)"),
    ("=SUM($A$2:A$6)", "delete_rows", (1,), "H19", "=SUM($A$1:A$5)"),
    ("=SUM(A2:A6)", "delete_rows", (7, 2), "H18", "=SUM(A2:A6)"),
    ("=SUM(A5:A5)", "delete_rows", (5,), "H19", "=SUM(#REF!)"),
    ("=SUM(A5:A9)", "delete_rows", (9,), "H19", "=SUM(A5:A8)"),
    ("=SUM(A5:A9)", "delete_rows", (5,), "H19", "=SUM(A5:A8)"),
    ("=SUM(A5:A9)", "delete_rows", (3, 4), "H16", "=SUM(A3:A5)"),
    ("=SUM(A3:B4)*H19", "delete_rows", (4,), "H19", "=SUM(A3:B3)*H18"),
    ('="A5"&A5', "insert_rows", (1,), "H21", '="A5"&A6'),
    ("=#REF!+A5", "insert_rows", (1,), "H21", "=#REF!+A6"),
    ("=SUM(B2:C3,A10)", "delete_rows", (2, 2), "H18", "=SUM(#REF!,A8)"),
    ("=SUM(A1:A1048576)", "insert_rows", (1,), "H21", "=SUM(A2:A1048576)"),
    ("=A1048576", "insert_rows", (1,), "H21", "=#REF!"),
    ("=SUM(A1:A1048576)", "insert_rows", (5, 2), "H22", "=SUM(A1:A1048576)"),
    ("=SUM(A1048575:A1048576)", "insert_rows", (1, 2), "H22", "=SUM(#REF!)"),
]


@pytest.mark.parametrize("formula,op,args,where,want", ROW_CASES)
def test_row_reference_rewriting(formula, op, args, where, want):
    s = sheet(H20=formula)
    getattr(s, op)(*args)
    assert s.formula(where) == want
    if where != "H20":
        assert s.formula("H20") == ""


COL_CASES = [
    ("A30", "=C1", "insert_cols", ("C",), "A30", "=D1"),
    ("A30", "=SUM(B1:D1)", "insert_cols", ("C", 2), "A30", "=SUM(B1:F1)"),
    ("A30", "=SUM(B1:D1)", "insert_cols", ("B",), "A30", "=SUM(C1:E1)"),
    ("A30", "=SUM(B1:D1)", "insert_cols", ("E",), "A30", "=SUM(B1:D1)"),
    ("A30", "=SUM(B1:D1)", "delete_cols", ("B",), "A30", "=SUM(B1:C1)"),
    ("A30", "=SUM(B1:D1)", "delete_cols", ("B", 3), "A30", "=SUM(#REF!)"),
    ("A30", "=SUM(B2:D9)", "delete_cols", ("C",), "A30", "=SUM(B2:C9)"),
    ("A30", "=SUM(AA1:AC1)", "delete_cols", ("Z", 2), "A30", "=SUM(Z1:AA1)"),
    ("A30", "=Z1+AA1", "insert_cols", ("B",), "A30", "=AA1+AB1"),
    ("A30", "=AZ1", "insert_cols", ("b",), "A30", "=BA1"),
    ("A30", "=ZZ1", "insert_cols", ("C",), "A30", "=AAA1"),
    ("A30", "=AA1", "delete_cols", ("B",), "A30", "=Z1"),
    ("A30", "=$C$1+C$1", "insert_cols", ("A",), "B30", "=$D$1+D$1"),
    ("A30", "=XFD1", "insert_cols", ("B",), "A30", "=#REF!"),
    ("A30", "=SUM(C1:E1)", "delete_cols", ("aa",), "A30", "=SUM(C1:E1)"),
    ("A30", "=C5", "delete_cols", ("C",), "A30", "=#REF!"),
    ("C30", "=A1+$B$1+D1", "delete_cols", ("A",), "B30", "=#REF!+$A$1+C1"),
]


@pytest.mark.parametrize("at,formula,op,args,where,want", COL_CASES)
def test_column_reference_rewriting(at, formula, op, args, where, want):
    s = sheet(**{at: formula})
    getattr(s, op)(*args)
    assert s.formula(where) == want
    if where != at:
        assert s.formula(at) == ""


def test_insert_rows_moves_cells_and_expands_ranges():
    s = sheet(A1="1", A2="2", A3="3", B1="=SUM(A1:A3)")
    s.insert_rows(2)
    assert [s.get(f"A{i}") for i in range(1, 5)] == [1, None, 2, 3]
    assert s.formula("B1") == "=SUM(A1:A4)" and s.get("B1") == 6
    s.set("A2", "10")
    assert s.get("B1") == 16


def test_delete_rows_shifts_cells_and_refs():
    s = sheet(A1="=A3", A2="x", A3="7")
    s.delete_rows(2)
    assert s.formula("A1") == "=A2" and s.get("A1") == 7
    assert s.get("A2") == 7 and s.get("A3") is None


def test_formula_cell_moving_with_its_refs():
    s = sheet(A5="=A4", A4="1")
    s.insert_rows(4)
    assert s.formula("A6") == "=A5" and s.get("A6") == 1 and s.get("A5") == 1
    t = sheet(A5="=A4", A4="1")
    t.insert_rows(5)
    assert t.formula("A6") == "=A4" and t.get("A6") == 1 and t.get("A5") is None


def test_absolute_references_move_too():
    s = sheet(C1="=$A$3*2", A3="4")
    s.insert_rows(1)
    assert s.formula("C2") == "=$A$4*2" and s.get("C2") == 8
    s.delete_rows(1)
    assert s.formula("C1") == "=$A$3*2" and s.get("C1") == 8


def test_insert_cols_moves_cells():
    s = sheet(B1="2", C1="=B1*2")
    s.insert_cols("A")
    assert s.get("B1") is None and s.get("C1") == 2
    assert s.formula("D1") == "=C1*2" and s.get("D1") == 4


def test_delete_cols_removes_formula_column():
    s = sheet(A1="1", B1="=A1+1", C1="=B1+1")
    s.delete_cols("B")
    assert s.formula("B1") == "=#REF!+1" and s.get("B1") == REF and s.get("C1") is None


def test_insert_pushing_cell_off_sheet_raises():
    s = sheet(A1048576="x", B1="=A1")
    with pytest.raises(ValueError):
        s.insert_rows(1)
    assert s.get("A1048576") == "x" and s.formula("B1") == "=A1"
    t = sheet(XFD1="y")
    with pytest.raises(ValueError):
        t.insert_cols("A")
    assert t.get("XFD1") == "y"
    u = sheet(A1048575="z")
    u.insert_rows(1)
    assert u.get("A1048576") == "z"


def test_bad_arguments():
    s = sheet(A1="1")
    for call in [lambda: s.insert_rows(0), lambda: s.insert_rows(1, 0), lambda: s.insert_rows(1048577),
                 lambda: s.delete_rows(1048576, 2), lambda: s.delete_rows(0), lambda: s.insert_rows(1, -1),
                 lambda: s.insert_cols("A1"), lambda: s.insert_cols(""), lambda: s.delete_cols("XFE"),
                 lambda: s.delete_cols("XFD", 2)]:
        with pytest.raises(ValueError):
            call()
    assert s.get("A1") == 1
    s.delete_rows(1048576)
    s.delete_cols("XFD")
    assert s.get("A1") == 1
