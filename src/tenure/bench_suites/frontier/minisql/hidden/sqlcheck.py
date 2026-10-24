"""Oracle helpers for the minisql hidden tests.

Every check runs the same setup statements and the same SQL on a fresh ``sqlite3.connect(':memory:')``
and on a fresh ``minisql.connect()`` and compares rows (values and Python types; REAL with a small
relative tolerance), rowcount for INSERT/UPDATE/DELETE, whether an error happens, and - only in the
tests about result column names - the column names.
Row order is compared only when the test says the ORDER BY fully determines it.
"""

from __future__ import annotations

import math
import sqlite3

import pytest

import minisql

EMP = [
    "CREATE TABLE emp (id INTEGER, name TEXT, dept TEXT, salary INTEGER, bonus REAL, manager INTEGER)",
    "INSERT INTO emp VALUES (1, 'Alice', 'eng', 120, 10.5, NULL)",
    "INSERT INTO emp VALUES (2, 'bob', 'eng', 100, NULL, 1)",
    "INSERT INTO emp VALUES (3, 'Carol', 'sales', 90, 5.0, 1)",
    "INSERT INTO emp VALUES (4, 'dave', 'sales', NULL, 2.5, 3)",
    "INSERT INTO emp VALUES (5, 'Eve', NULL, 70, NULL, 3)",
    "INSERT INTO emp VALUES (6, 'frank', 'hr', 70, 0.0, 1)",
    "INSERT INTO emp VALUES (7, 'Grace', 'eng', 150, 20.0, 2)",
    "CREATE TABLE dept (code TEXT, title TEXT, floor INTEGER)",
    "INSERT INTO dept VALUES ('eng', 'Engineering', 3), ('sales', 'Sales', 1), ('ops', 'Operations', 2), ('hr', 'People', NULL)",
    "CREATE TABLE proj (pid INTEGER, emp_id INTEGER, pname TEXT, hours REAL)",
    "INSERT INTO proj VALUES (10, 1, 'apollo', 12.5), (11, 1, 'zeus', 3.0), (12, 2, 'apollo', 7.25), "
    "(13, 7, 'hermes', NULL), (14, 9, 'ghost', 1.0), (15, 3, 'zeus', 4.0)",
]

MIX = [
    "CREATE TABLE mix (id INTEGER, v)",
    "INSERT INTO mix VALUES (1, 3), (2, 'b'), (3, NULL), (4, 2.5), (5, 'A'), (6, 10), (7, '10'), (8, -1), (9, ''), (10, 'a')",
]

AFF = [
    "CREATE TABLE n (id INTEGER, i INTEGER, r REAL, s TEXT, b, num NUMERIC)",
    "INSERT INTO n VALUES (1, 5, 5, '5', 5, '5')",
    "INSERT INTO n VALUES (2, 10, 2.5, '10', '10', '3.0')",
    "INSERT INTO n VALUES (3, 9, 9.0, '9', 9.0, 'x')",
    "INSERT INTO n VALUES (4, NULL, NULL, NULL, NULL, NULL)",
    "INSERT INTO n VALUES (5, 'abc', '1e1', ' 7', 'abc', 12)",
]


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if type(a) is not type(b):
        return False
    if isinstance(a, float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    return a == b


def _key(v):
    if v is None:
        return (0, 0, "")
    if isinstance(v, str):
        return (2, 0, v)
    return (1, v, "")


def assert_rows(expected: list, got, ordered: bool, sql: str = "") -> None:
    assert isinstance(got, list), f"fetchall() 은 list 를 돌려줘야 한다: {type(got).__name__}"
    for r in got:
        assert isinstance(r, tuple), f"행은 tuple 이어야 한다: {r!r}"
    if not ordered:
        expected = sorted(expected, key=lambda r: [_key(v) for v in r])
        got = sorted(got, key=lambda r: [_key(v) if isinstance(v, (type(None), int, float, str)) else (3, 0, repr(v))
                                         for v in r])
    ok = len(expected) == len(got) and all(
        len(x) == len(y) and all(_same(p, q) for p, q in zip(x, y)) for x, y in zip(expected, got))
    assert ok, f"{sql}\n기대(sqlite3): {expected!r}\n실제(minisql): {got!r}"


def connections(setup):
    s = sqlite3.connect(":memory:")
    m = minisql.connect()
    for stmt in setup:
        s.execute(stmt)
        m.execute(stmt)
    return s, m


def fetch(con, sql, params=()):
    cur = con.execute(sql, params)
    names = None if cur.description is None else [d[0] for d in cur.description]
    rows = cur.fetchall()
    return names, rows


def check(setup, sql, params=(), ordered=False, names=False):
    """Same result on sqlite3 and minisql (column names only when names=True)."""
    s, m = connections(setup)
    exp_names, exp_rows = fetch(s, sql, params)
    got_names, got_rows = fetch(m, sql, params)
    if names:
        assert got_names == exp_names, f"{sql}\n열 이름 기대: {exp_names!r}\n실제: {got_names!r}"
    assert_rows(exp_rows, got_rows, ordered, sql)


def check_dml(setup, stmts, query, ordered=False, params_list=None):
    """Run DML statements on both (rowcount and description compared), then compare a query."""
    s, m = connections(setup)
    for k, st in enumerate(stmts):
        params = params_list[k] if params_list else ()
        cs = s.execute(st, params)
        cm = m.execute(st, params)
        assert cm.rowcount == cs.rowcount, f"{st}\nrowcount 기대: {cs.rowcount}, 실제: {cm.rowcount}"
        assert cm.description is None and cs.description is None, f"{st}: description 은 None 이어야 한다"
    _, exp_rows = fetch(s, query)
    _, got_rows = fetch(m, query)
    assert_rows(exp_rows, got_rows, ordered, query)


def check_error(setup, sql, params=()):
    """sqlite3 raises an error; minisql must raise minisql.Error."""
    s, m = connections(setup)
    with pytest.raises(sqlite3.Error):
        s.execute(sql, params).fetchall()
    with pytest.raises(minisql.Error):
        m.execute(sql, params).fetchall()
