import pytest

from sheet import Error, Sheet

REF, NAME = Error("#REF!"), Error("#NAME?")


def sheet(**cells):
    s = Sheet()
    for k, v in cells.items():
        s.set(k, v)
    return s


# ---------------------------------------------------------------- copy
def test_copy_shifts_relative_refs():
    s = sheet(A1="1", A2="2", B1="=A1*10")
    s.copy("B1", "B2")
    assert s.formula("B2") == "=A2*10" and s.get("B2") == 20
    assert s.formula("B1") == "=A1*10"


def test_copy_mixed_absolute_refs():
    s = sheet(C3="=$A1+A$1+$A$1+A1")
    s.copy("C3", "D5")
    assert s.formula("D5") == "=$A3+B$1+$A$1+B3"


def test_copy_block_keeps_internal_relations():
    s = sheet(A1="1", A2="=A1+1")
    s.copy("A1:A2", "C5")
    assert s.formula("C5") == "1" and s.formula("C6") == "=C5+1" and s.get("C6") == 2


@pytest.mark.parametrize("src_cell,formula,dst,want", [
    ("B2", "=A1", "A1", "=#REF!"),
    ("C1", "=A1+B1", "B1", "=#REF!+A1"),
    ("B2", "=SUM(A1:B1)", "A2", "=SUM(#REF!)"),
    ("B1", "=XFD1", "C1", "=#REF!"),
    ("A2", "=A1048576+A1", "A3", "=#REF!+A2"),
    ("B2", "=$A1+A$1", "A1", "=#REF!+#REF!"),
    ("C2", "=SUM($A$1:B1)", "B1", "=SUM(#REF!)"),
])
def test_copy_out_of_bounds_becomes_ref_error(src_cell, formula, dst, want):
    s = sheet(**{src_cell: formula})
    s.copy(src_cell, dst)
    assert s.formula(dst) == want and s.get(dst) == REF


def test_copy_renormalizes_range_corners():
    s = sheet(A5="=SUM(B1:$C1)")
    s.copy("A5", "C5")
    assert s.formula("C5") == "=SUM($C1:D1)"


def test_copy_does_not_touch_strings_function_names_or_ref_errors():
    s = sheet(B1='="A1"&A1&AB12(A1)', C1="=#REF!+A1")
    s.copy("B1:C1", "B2")
    assert s.formula("B2") == '="A1"&A2&AB12(A2)' and s.get("B2") == NAME
    assert s.formula("C2") == "=#REF!+A2" and s.get("C2") == REF


def test_copy_empty_source_cell_clears_destination():
    s = sheet(A1="x", D1="1", E1="2")
    s.copy("A1:B1", "D1")
    assert s.get("D1") == "x" and s.get("E1") is None and s.formula("E1") == ""


def test_copy_constant_text_verbatim():
    s = sheet(A1="'007", A2="1.50", A3="true")
    s.copy("A1:A3", "C1")
    assert [s.formula(r) for r in ("C1", "C2", "C3")] == ["'007", "1.50", "true"]
    assert s.get("C1") == "007" and s.get("C2") == 1.5 and s.get("C3") is True


def test_copy_overlapping_uses_snapshot():
    s = sheet(A1="1", A2="=A1+1", A3="=A2+1")
    s.copy("A1:A2", "A2")
    assert s.formula("A2") == "1" and s.formula("A3") == "=A2+1"
    assert s.get("A1") == 1 and s.get("A2") == 1 and s.get("A3") == 2


def test_copy_overlapping_down_shifts_whole_block():
    s = sheet(A1="a", A2="b", A3="c")
    s.copy("A1:A3", "A2")
    assert [s.get(f"A{i}") for i in range(1, 5)] == ["a", "a", "b", "c"]


def test_copy_reversed_source_corners():
    s = sheet(A1="1", B1="=A1+1", A2="=B1*2")
    s.copy("B2:A1", "D1")
    assert s.formula("E1") == "=D1+1" and s.formula("D2") == "=E1*2" and s.get("D2") == 4


def test_copy_outside_sheet_raises_and_changes_nothing():
    s = sheet(A1="1", B1="2", XFD1="keep")
    with pytest.raises(ValueError):
        s.copy("A1:B1", "XFD1")
    with pytest.raises(ValueError):
        s.copy("A1:A2", "C1048576")
    assert s.get("XFD1") == "keep" and s.get("C1048576") is None


def test_copy_absolute_range_unchanged_and_recomputed():
    s = sheet(A1="1", A2="2", A3="3", B1="=SUM($A$1:$A$3)*A1")
    s.copy("B1", "B3")
    assert s.formula("B3") == "=SUM($A$1:$A$3)*A3" and s.get("B3") == 18


# ---------------------------------------------------------------- move
def test_move_references_follow():
    s = sheet(A1="5", B1="=A1*2")
    s.move("A1", "C3")
    assert s.formula("B1") == "=C3*2" and s.get("B1") == 10
    assert s.get("A1") is None and s.get("C3") == 5


def test_move_formula_keeps_outside_refs():
    s = sheet(A1="1", B1="=A1+1")
    s.move("B1", "D5")
    assert s.formula("D5") == "=A1+1" and s.get("D5") == 2 and s.get("B1") is None


def test_move_block_internal_refs_follow():
    s = sheet(A1="1", A2="=A1+1")
    s.move("A1:A2", "C1")
    assert s.formula("C2") == "=C1+1" and s.get("C2") == 2
    assert s.get("A1") is None and s.get("A2") is None


def test_move_overwritten_target_refs_become_ref_error():
    s = sheet(A1="1", B1="2", C1="=B1")
    s.move("A1", "B1")
    assert s.formula("C1") == "=#REF!" and s.get("C1") == REF and s.get("B1") == 1


def test_move_absolute_refs_follow():
    s = sheet(A1="4", C1="=$A$1+A$1")
    s.move("A1", "B5")
    assert s.formula("C1") == "=$B$5+B$5" and s.get("C1") == 8


def test_move_range_inside_source_shifts_partial_range_stays():
    s = sheet(A1="1", A2="2", A3="3", B1="=SUM(A1:A2)", B2="=SUM(A1:A3)")
    s.move("A1:A2", "C1")
    assert s.formula("B1") == "=SUM(C1:C2)" and s.get("B1") == 3
    assert s.formula("B2") == "=SUM(A1:A3)" and s.get("B2") == 3


def test_move_overlapping():
    s = sheet(A1="1", A2="2", A3="3", A4="4", B1="=A1+A4", B2="=SUM(A1:A3)")
    s.move("A1:A3", "A2")
    assert s.formula("B1") == "=A2+#REF!" and s.get("B1") == REF
    assert s.formula("B2") == "=SUM(A2:A4)" and s.get("B2") == 6
    assert s.get("A1") is None and [s.get(f"A{i}") for i in (2, 3, 4)] == [1, 2, 3]


def test_moved_formula_pointing_at_target_becomes_ref_error():
    s = sheet(A1="=B1", B1="5")
    s.move("A1", "B1")
    assert s.formula("B1") == "=#REF!" and s.get("B1") == REF and s.get("A1") is None


def test_move_empty_source_cells_clear_target():
    s = sheet(A1="x", D1="1", E1="2", F1="=E1")
    s.move("A1:B1", "D1")
    assert s.get("D1") == "x" and s.get("E1") is None
    assert s.formula("F1") == "=#REF!"


def test_move_outside_sheet_raises():
    s = sheet(A1="1", B1="=A1")
    with pytest.raises(ValueError):
        s.move("A1:A2", "A1048576")
    assert s.formula("B1") == "=A1" and s.get("A1") == 1
