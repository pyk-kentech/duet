import os
import subprocess
import sys

from sheet import Error, Sheet

CYCLE, NAME, REF = Error("#CYCLE!"), Error("#NAME?"), Error("#REF!")


def test_changes_propagate():
    s = Sheet()
    s.set("A1", "1")
    s.set("B1", "=A1+1")
    s.set("C1", "=B1*2")
    assert s.get("C1") == 4
    s.set("A1", "5")
    assert s.get("B1") == 6 and s.get("C1") == 12
    s.set("A1", "")
    assert s.get("B1") == 1 and s.get("C1") == 2
    s.set("B1", "10")
    assert s.get("C1") == 20 and s.formula("B1") == "10"


def test_range_dependents_update():
    s = Sheet()
    s.set("D1", "=SUM(A1:A3)")
    s.set("D2", "=COUNTA(A1:A3)")
    assert s.get("D1") == 0 and s.get("D2") == 0
    s.set("A2", "7")
    assert s.get("D1") == 7 and s.get("D2") == 1
    s.set("A3", "=A2*2")
    assert s.get("D1") == 21 and s.get("D2") == 2


def test_two_cell_cycle_and_recovery():
    s = Sheet()
    s.set("A1", "=B1")
    s.set("B1", "=A1")
    s.set("C1", "=A1+1")
    s.set("D1", "=IFERROR(A1,0)")
    s.set("E1", "=COUNT(A1:B1)")
    s.set("F1", "=COUNTA(A1:B1)")
    assert s.get("A1") == CYCLE and s.get("B1") == CYCLE
    assert s.get("C1") == CYCLE and s.get("D1") == 0 and s.get("E1") == 0 and s.get("F1") == 2
    s.set("B1", "5")
    assert s.get("A1") == 5 and s.get("C1") == 6 and s.get("D1") == 5 and s.get("E1") == 2


def test_self_references():
    s = Sheet()
    s.set("A1", "=A1+1")
    s.set("A5", "=SUM(A2:A10)")
    s.set("B1", "=A5")
    assert s.get("A1") == CYCLE and s.get("A5") == CYCLE and s.get("B1") == CYCLE
    s.set("A5", "=SUM(A2:A4)")
    assert s.get("A5") == 0 and s.get("B1") == 0


def test_cycle_is_static_even_through_unused_branch():
    s = Sheet()
    s.set("A1", "=IF(TRUE,1,B1)")
    s.set("B1", "=A1")
    assert s.get("A1") == CYCLE and s.get("B1") == CYCLE


def test_cycle_through_unknown_function_arguments():
    s = Sheet()
    s.set("A1", "=FOO(B1)")
    s.set("B1", "=A1")
    assert s.get("A1") == CYCLE and s.get("B1") == CYCLE
    s.set("B1", "1")
    assert s.get("A1") == NAME


def test_three_cell_cycle_broken_by_clearing():
    s = Sheet()
    s.set("A1", "=B1")
    s.set("B1", "=C1")
    s.set("C1", "=A1+1")
    s.set("D1", "=SUM(A1:C1)")
    assert [s.get(r) for r in ("A1", "B1", "C1", "D1")] == [CYCLE] * 4
    s.set("C1", "")
    assert s.get("A1") == 0 and s.get("B1") == 0 and s.get("D1") == 0


def test_copy_can_create_a_cycle():
    s = Sheet()
    s.set("A1", "=$B$1")
    s.set("B1", "3")
    assert s.get("A1") == 3
    s.copy("A1", "B1")
    assert s.formula("B1") == "=$B$1"
    assert s.get("B1") == CYCLE and s.get("A1") == CYCLE


def test_delete_rows_breaks_cycle():
    s = Sheet()
    s.set("B1", "1")
    s.set("B2", "=A1")
    s.set("B3", "3")
    s.set("A1", "=SUM(B1:B3)")
    assert s.get("A1") == CYCLE and s.get("B2") == CYCLE
    s.delete_rows(2)
    assert s.formula("A1") == "=SUM(B1:B2)" and s.get("A1") == 4


def test_cycle_cell_inside_range_of_sumif_resized_area():
    s = Sheet()
    s.set("A1", "1")
    s.set("A2", "1")
    s.set("B1", "5")
    # sum_range B1 은 B1:B2 로 맞춰지므로 B2 자신을 포함한다
    s.set("B2", '=SUMIF(A1:A2,">0",B1)')
    assert s.get("B2") == CYCLE
    s.set("B2", '=SUMIF(A1:A1,">0",B1)')
    assert s.get("B2") == 5


CHAIN = """
import time
from sheet import Sheet
s = Sheet()
n = 10000
t0 = time.perf_counter()
s.set("A1", "1")
for i in range(2, n + 1):
    s.set(f"A{i}", f"=A{i - 1}+1")
assert s.get(f"A{n}") == n
s.set("A1", "0")
assert s.get(f"A{n}") == n - 1
assert s.get("A5000") == 4999
s.set("A1", "=A10000")
assert str(s.get("A10000")) == "#CYCLE!" and str(s.get("A1")) == "#CYCLE!"
el = time.perf_counter() - t0
assert el < 10, el
print("OK")
"""

SPARSE = """
import time
from sheet import Sheet
s = Sheet()
s.set("A1", "1")
s.set("B50000", "3")
s.set("J100000", "2")
s.set("C7", "x")
t0 = time.perf_counter()
s.set("Z1", "=SUM(A1:J100000)")
s.set("Z2", "=COUNT(A1:J100000)")
s.set("Z3", "=COUNTA(A1:J100000)")
s.set("Z4", '=COUNTIF(A1:J100000,"")')
s.set("Z5", "=MAX(A1:XFD1048576)")
s.set("Z6", "=AVERAGE(B1:B1048576)")
assert s.get("Z1") == 6 and s.get("Z2") == 3 and s.get("Z3") == 4, (s.get("Z1"), s.get("Z2"), s.get("Z3"))
assert s.get("Z4") == 1000000 - 4, s.get("Z4")
assert s.get("Z6") == 3, s.get("Z6")
s.set("B50000", "30")
assert s.get("Z1") == 33 and s.get("Z6") == 30
assert str(s.get("Z5")) == "#CYCLE!"
el = time.perf_counter() - t0
assert el < 3, el
print("OK")
"""


def _run_isolated(code: str, timeout: float) -> None:
    """느린 구현이 채점 전체 시간을 다 쓰지 않게 따로 프로세스에서 시간 제한을 두고 돌린다."""
    try:
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=timeout,
                           env=os.environ.copy())
    except subprocess.TimeoutExpired:
        raise AssertionError(f"{timeout}초 안에 끝나지 않았다") from None
    assert r.returncode == 0 and "OK" in r.stdout, (r.stdout + r.stderr)[-2000:]


def test_long_chain_without_recursion_error():
    _run_isolated(CHAIN, 40)


def test_huge_sparse_ranges_are_fast():
    _run_isolated(SPARSE, 30)


def test_ref_error_after_delete_propagates():
    s = Sheet()
    s.set("A1", "1")
    s.set("A2", "=A1*2")
    s.set("A3", "=A2+1")
    s.set("B1", "=A3*10")
    s.delete_rows(1)
    assert s.formula("A1") == "=#REF!*2" and s.get("A1") == REF
    assert s.get("A2") == REF and s.get("B1") is None
