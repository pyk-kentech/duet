from sheet import Error, Sheet

REF, DIV0 = Error("#REF!"), Error("#DIV/0!")


def sheet(**cells):
    s = Sheet()
    for k, v in cells.items():
        s.set(k, v)
    return s


def test_budget_insert_row():
    s = sheet(A1="Item", B1="Cost", A2="rent", B2="1000", A3="food", B3="250.5", A4="fun", B4="'100",
              B5="=SUM(B2:B4)", B6="=B2+B3+B4", B7="=AVERAGE(B2:B4)", B8='=COUNTIF(A2:A4,"f*")')
    assert [s.get(f"B{i}") for i in range(5, 9)] == [1250.5, 1350.5, 625.25, 2]
    s.insert_rows(3)
    s.set("A3", "misc")
    s.set("B3", "50")
    assert s.formula("B6") == "=SUM(B2:B5)" and s.get("B6") == 1300.5
    assert s.formula("B7") == "=B2+B4+B5" and s.get("B7") == 1350.5
    assert s.formula("B8") == "=AVERAGE(B2:B5)" and s.get("B8") == 433.5
    assert s.formula("B9") == '=COUNTIF(A2:A5,"f*")' and s.get("B9") == 2


def test_running_total_copy_then_delete_row():
    s = sheet(A1="1", A2="2", A3="3", A4="4", A5="5", B1="=A1", B2="=B1+A2")
    for r in (3, 4, 5):
        s.copy("B2", f"B{r}")
    assert s.formula("B5") == "=B4+A5" and s.get("B5") == 15
    s.delete_rows(3)
    assert s.formula("B3") == "=#REF!+A3" and s.get("B3") == REF
    assert s.formula("B4") == "=B3+A4" and s.get("B4") == REF
    assert s.get("B2") == 3


def test_multiplication_table_then_insert_and_delete():
    s = sheet(B1="1", C1="2", D1="3", A2="1", A3="2", A4="3", B2="=$A2*B$1")
    for col in "BCD":
        for row in (2, 3, 4):
            if (col, row) != ("B", 2):
                s.copy("B2", f"{col}{row}")
    assert s.formula("D4") == "=$A4*D$1" and s.get("D4") == 9 and s.get("C3") == 4
    s.insert_cols("C")
    assert s.formula("E4") == "=$A4*E$1" and s.get("E4") == 9 and s.get("C4") is None
    assert s.formula("D3") == "=$A3*D$1" and s.get("D3") == 4
    s.delete_rows(1)
    assert s.formula("E3") == "=$A3*#REF!" and s.get("E3") == REF


def test_sumif_range_grows_with_inserted_row():
    s = sheet(A1="x", A2="y", A3="x", A4="z", B1="1", B2="2", B3="3", B4="4", C1='=SUMIF(A1:A4,"x",B1)')
    assert s.get("C1") == 4
    s.insert_rows(3)
    assert s.formula("C1") == '=SUMIF(A1:A5,"x",B1)'
    s.set("A3", "X")
    s.set("B3", "10")
    assert s.get("C1") == 14


def test_error_recovers_after_input_change():
    s = sheet(A1="0", B1="=10/A1", C1='=IFERROR(B1,"bad")', D1="=COUNT(B1:C1)")
    assert s.get("B1") == DIV0 and s.get("C1") == "bad" and s.get("D1") == 0
    s.set("A1", "4")
    assert s.get("B1") == 2.5 and s.get("C1") == 2.5 and s.get("D1") == 2


def test_move_then_copy():
    s = sheet(A1="1", A2="=A1*2", E1="=A2+1")
    s.move("A1:A2", "C3")
    assert s.formula("C4") == "=C3*2" and s.formula("E1") == "=C4+1" and s.get("E1") == 3
    s.copy("C4", "D4")
    assert s.formula("D4") == "=D3*2" and s.get("D4") == 0


def test_delete_cols_shrinks_then_ref_error_survives_copy():
    s = sheet(A1="1", B1="2", C1="3", D1="4", E1="5", A2="=SUM(B1:D1)")
    assert s.get("A2") == 9
    s.delete_cols("D")
    assert s.formula("A2") == "=SUM(B1:C1)" and s.get("A2") == 5
    s.delete_cols("B", 2)
    assert s.formula("A2") == "=SUM(#REF!)" and s.get("A2") == REF
    s.copy("A2", "B2")
    assert s.formula("B2") == "=SUM(#REF!)" and s.get("B1") == 5


def test_text_numbers_through_pipeline():
    s = sheet(A1="'10", A2="20", A3="=A1&A2", A4="=A3+1", A5="=SUM(A1:A3)", A6="=SUM(A1,A3)", A7='=A3="1020"')
    assert s.get("A3") == "1020" and s.get("A4") == 1021
    assert s.get("A5") == 20 and s.get("A6") == 0 and s.get("A7") is True
    s.set("A8", "=SUM(A1+0,A3+0)")
    assert s.get("A8") == 1030


CYCLE, VALUE, NAME = Error("#CYCLE!"), Error("#VALUE!"), Error("#NAME?")


def test_grade_book_text_score_compares_as_text():
    s = sheet(A1="name", B1="score", C1="grade", A2="kim", B2="95", A3="lee", B3="'85", A4="park", A5="choi",
              B5="72", C2='=IF(B2>=90,"A",IF(B2>=80,"B","C"))')
    for r in (3, 4, 5):
        s.copy("C2", f"C{r}")
    assert [s.get(f"C{r}") for r in range(2, 6)] == ["A", "A", "C", "C"]
    assert s.formula("C4") == '=IF(B4>=90,"A",IF(B4>=80,"B","C"))'
    s.set("F10", '=COUNTIF(C2:C5,"A")')
    s.set("F11", "=AVERAGE(B2:B5)")
    s.set("F12", '=SUMIF(C2:C5,"c",B2)')
    s.set("F13", "=COUNT(B2:B5)")
    s.set("F14", "=COUNTA(B2:B5)")
    assert [s.get(f"F{r}") for r in range(10, 15)] == [2, 83.5, 72, 2, 3]
    s.delete_rows(3)
    assert s.formula("F9") == '=COUNTIF(C2:C4,"A")' and s.formula("F11") == '=SUMIF(C2:C4,"c",B2)'
    assert [s.get(f"F{r}") for r in range(9, 14)] == [1, 83.5, 72, 2, 2]
    s.set("B3", "'100")
    assert s.get("C3") == "A" and s.get("F9") == 2 and s.get("F12") == 2 and s.get("F13") == 3


def test_percent_text_is_not_a_number():
    s = sheet(A1="rate", B1="10%", A2="200", A3="'50", C2="=A2*$B$1", C3="=A3*$B$1", C4="=SUM(C2:C3)")
    assert s.get("B1") == "10%" and s.get("C2") == VALUE and s.get("C3") == VALUE and s.get("C4") == VALUE
    s.set("B1", "=10%")
    assert s.get("C2") == 20 and s.get("C3") == 5 and s.get("C4") == 25
    s.insert_rows(1)
    assert s.formula("C3") == "=A3*$B$2" and s.formula("C5") == "=SUM(C3:C4)" and s.get("C5") == 25
    s.insert_cols("B")
    assert s.formula("D3") == "=A3*$C$2" and s.formula("D5") == "=SUM(D3:D4)" and s.get("D5") == 25


def test_number_text_formatting_pipeline():
    s = sheet(A1="=1/3", A2="=0.1+0.2", B1='=LEN(A1&"")', B2='=A2&""', B3='=ROUND(A2,2)&""', B4='=ROUND(A1,0)&"x"',
              B5="=CONCAT(A1:A2)", B6='=A2*10&""')
    assert s.get("B1") == 18 and s.get("B2") == "0.30000000000000004" and s.get("B3") == "0.3"
    assert s.get("B4") == "0x" and s.get("B5") == "0.33333333333333330.30000000000000004"
    assert s.get("B6") == "3.0000000000000004"


def test_move_into_range_creates_cycle_then_delete_column():
    s = sheet(A1="=SUM(B1:B3)", B1="1", B2="2", C1="=A1")
    assert s.get("A1") == 3 and s.get("C1") == 3
    s.move("C1", "B3")
    assert s.formula("B3") == "=A1" and s.formula("A1") == "=SUM(B1:B3)" and s.get("C1") is None
    assert s.get("A1") == CYCLE and s.get("B3") == CYCLE
    s.delete_cols("B")
    assert s.formula("A1") == "=SUM(#REF!)" and s.get("A1") == REF and s.get("B1") is None


def test_sumif_sum_range_through_column_changes():
    s = sheet(A1="x", A2="y", A3="x", C1="1", C2="2", C3="3", E1='=SUMIF(A1:A3,"x",C1)')
    assert s.get("E1") == 4
    s.insert_cols("B")
    assert s.formula("F1") == '=SUMIF(A1:A3,"x",D1)' and s.get("F1") == 4
    s.delete_cols("D")
    assert s.formula("E1") == '=SUMIF(A1:A3,"x",#REF!)' and s.get("E1") == REF


def test_error_order_changes_after_move():
    s = sheet(A1="1", B1='="a"+1', A2="=1/0", B2="2", C1="=SUM(A1:B2)", C2="=IFERROR(C1,-1)")
    assert s.get("C1") == VALUE and s.get("C2") == -1
    s.move("B1", "D1")
    assert s.formula("C1") == "=SUM(A1:B2)" and s.get("C1") == DIV0 and s.get("D1") == VALUE
    s.set("A2", "3")
    assert s.get("C1") == 6 and s.get("C2") == 6


def test_absolute_anchor_rows_deleted():
    s = sheet(A1="rate", B1="2", A2="1", A3="2", A4="3", A5="4", A6="5", B2="=A2*$B$1")
    for r in range(3, 7):
        s.copy("B2", f"B{r}")
    s.set("B7", "=SUM(B2:B6)")
    assert s.get("B7") == 30
    s.delete_rows(3, 2)
    assert s.formula("B5") == "=SUM(B2:B4)" and s.get("B5") == 20
    assert s.formula("B3") == "=A3*$B$1" and s.get("B3") == 8
    s.delete_rows(1)
    assert s.formula("B1") == "=A1*#REF!" and s.get("B1") == REF
    assert s.formula("B4") == "=SUM(B1:B3)" and s.get("B4") == REF


def test_unary_plus_text_through_functions():
    s = sheet(A1='=+"007"', A2="=A1+0", A3="=A1=7", A4='=A1="7"', A5="=-A1", A6="=A1&A2", A7="=SUM(A1,A2)",
              A8="=COUNT(A1,+A1)")
    assert s.get("A1") == "007" and s.get("A2") == 7 and s.get("A3") is False and s.get("A4") is False
    assert s.get("A5") == -7 and s.get("A6") == "0077" and s.get("A7") == 7 and s.get("A8") == 1


def test_overlapping_block_copy_with_mixed_refs():
    s = sheet(A1="1", A2="2", A3="3", B1="=A1*$A$1", B2="=A2*$A$1", B3="=SUM($A1:A$3)")
    s.copy("A1:B3", "B2")
    assert [s.formula(r) for r in ("B2", "B3", "B4")] == ["1", "2", "3"]
    assert s.formula("C2") == "=B2*$A$1" and s.formula("C3") == "=B3*$A$1" and s.formula("C4") == "=SUM($A2:B$3)"
    assert s.formula("B1") == "=A1*$A$1"
    assert [s.get(r) for r in ("B1", "C2", "C3", "C4")] == [1, 1, 2, 8]


def test_names_and_unknown_functions_survive_edits():
    s = sheet(A1="=foo(B1)+bar", B1="1")
    assert s.formula("A1") == "=FOO(B1)+BAR" and s.get("A1") == NAME
    s.insert_cols("A")
    assert s.formula("B1") == "=FOO(C1)+BAR" and s.get("B1") == NAME
    s.copy("B1", "B2")
    assert s.formula("B2") == "=FOO(C2)+BAR"
    s.set("C1", "=B1")
    assert s.get("B1") == CYCLE and s.get("C1") == CYCLE and s.get("B2") == NAME
