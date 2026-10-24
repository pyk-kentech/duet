"""Type affinity: column type names, conversion when storing, conversion before comparing."""

import pytest

from sqlcheck import AFF, check, check_dml

STORE_CASES = [
    ("INTEGER", "'5'"),
    ("INTEGER", "'5.0'"),
    ("INTEGER", "' 7 '"),
    ("INTEGER", "'2.5'"),
    ("INTEGER", "'abc'"),
    ("INTEGER", "5.0"),
    ("INTEGER", "'1e2'"),
    ("INTEGER", "''"),
    ("INTEGER", "'0x10'"),
    ("INTEGER", "'12abc'"),
    ("INTEGER", "'-0'"),
    ("INTEGER", "'+3'"),
    ("REAL", "'5'"),
    ("REAL", "3"),
    ("REAL", "'abc'"),
    ("REAL", "'.5'"),
    ("TEXT", "5"),
    ("TEXT", "2.50"),
    ("TEXT", "1.0"),
    ("TEXT", "NULL"),
    ("", "'5'"),
    ("", "5"),
    ("", "2.0"),
    ("NUMERIC", "'3.0'"),
    ("NUMERIC", "'0123'"),
    ("NUMERIC", "'4.5'"),
    ("INT", "'42'"),
    ("BIGINT", "'42'"),
    ("VARCHAR(10)", "12"),
    ("CHARACTER(20)", "1.5"),
    ("FLOATING POINT", "'5.0'"),
    ("STRING", "'0123'"),
    ("DOUBLE PRECISION", "'3'"),
    ("FLOAT", "7"),
    ("CHARINT", "'7'"),
    ("DECIMAL(10,2)", "'1.50'"),
    ("BLOB", "'5'"),
    ("CLOB", "5"),
    ("BOOLEAN", "'1'"),
    ("DATE", "'2024'"),
]


@pytest.mark.parametrize("ctype,value", STORE_CASES, ids=[f"{t or 'none'}-{v}" for t, v in STORE_CASES])
def test_storage_affinity(ctype, value):
    check([f"CREATE TABLE t (c {ctype})", f"INSERT INTO t VALUES ({value})"], "SELECT c, typeof(c) FROM t")


def test_update_applies_affinity():
    check_dml(AFF, ["UPDATE n SET i = '77', r = 4, s = 3.5, b = '8', num = '2.0' WHERE id = 1"],
              "SELECT i, typeof(i), r, typeof(r), s, typeof(s), b, typeof(b), num, typeof(num) FROM n WHERE id = 1")


def test_insert_select_applies_affinity():
    check_dml(AFF, ["CREATE TABLE t (x TEXT, y INTEGER)", "INSERT INTO t SELECT i, s FROM n"],
              "SELECT x, typeof(x), y, typeof(y) FROM t")


COMPARE_CASES = [
    "SELECT id FROM n WHERE i = '5'",
    "SELECT id FROM n WHERE s = 5",
    "SELECT id FROM n WHERE s = 5.0",
    "SELECT id FROM n WHERE i = '5.0'",
    "SELECT id FROM n WHERE s < 10",
    "SELECT id FROM n WHERE s > 7",
    "SELECT id FROM n WHERE b = '5'",
    "SELECT id FROM n WHERE b = 5",
    "SELECT id FROM n WHERE b = '10'",
    "SELECT id FROM n WHERE i = s",
    "SELECT id FROM n WHERE s = b",
    "SELECT id FROM n WHERE r = '2.5'",
    "SELECT id FROM n WHERE num = '3'",
    "SELECT id FROM n WHERE i > '7'",
    "SELECT id FROM n WHERE b > '7'",
    "SELECT id FROM n WHERE i IS '5'",
    "SELECT id FROM n WHERE i IN ('5', '9')",
    "SELECT id FROM n WHERE s IN (5, 9)",
    "SELECT id FROM n WHERE '5' IN (i)",
    "SELECT id FROM n WHERE 5 IN (s, b)",
    "SELECT id FROM n WHERE i BETWEEN '6' AND '10'",
    "SELECT id FROM n WHERE s BETWEEN 6 AND 10",
    "SELECT id, CASE i WHEN '5' THEN 'five' WHEN '9' THEN 'nine' ELSE 'other' END FROM n",
    "SELECT id, CASE s WHEN 10 THEN 'ten' ELSE 'other' END FROM n",
    "SELECT id FROM n WHERE i = (SELECT '9')",
    "SELECT id FROM n WHERE (SELECT s FROM n WHERE id = 1) = 5",
    "SELECT id FROM n WHERE s IN (SELECT 9)",
    "SELECT id FROM n WHERE i IN (SELECT '10')",
    "SELECT id FROM n WHERE s = CAST(9 AS TEXT)",
    "SELECT id FROM n WHERE CAST(i AS TEXT) = '10'",
    "SELECT id FROM n WHERE CAST(s AS INTEGER) = '10'",
    "SELECT id FROM n WHERE s || '' = 5",
    "SELECT id FROM n WHERE i + 0 = '5'",
    "SELECT id FROM n WHERE i > 'a'",
    "SELECT id FROM n WHERE i < 100",
    "SELECT id FROM n WHERE r = 10",
    "SELECT * FROM (SELECT id, i, i + 0 AS j FROM n) WHERE i = '9' OR j = '10'",
    "SELECT id FROM n WHERE i = ' 5 '",
    "SELECT id FROM n WHERE s IN (5.0, 9)",
    "SELECT max(s), min(s), max(i), min(b), max(num) FROM n",
]


@pytest.mark.parametrize("sql", COMPARE_CASES)
def test_comparison_affinity(sql):
    check(AFF, sql)


def test_comparison_affinity_with_parameter():
    check(AFF, "SELECT id FROM n WHERE i = ? OR s = ?", ("10", 9))


def test_join_between_integer_and_text_columns():
    check(AFF + ["CREATE TABLE k (code TEXT, val INTEGER)", "INSERT INTO k VALUES ('5', 1), ('10', 2), ('09', 3), ('abc', 4)"],
          "SELECT n.id, k.val FROM n JOIN k ON n.i = k.code")


def test_text_column_sorts_as_text():
    check(AFF, "SELECT id, s FROM n ORDER BY s, id", ordered=True)
    check(AFF, "SELECT id, i FROM n ORDER BY i DESC, id", ordered=True)
