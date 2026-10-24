import os
import sqlite3

import pytest

import minisql
from sqlcheck import EMP, check, check_dml, check_error, connections


def test_package_does_not_use_sqlite3():
    assert callable(getattr(minisql, "connect", None)), "minisql.connect 가 없다"
    roots = list(getattr(minisql, "__path__", []))
    assert roots, "minisql 은 패키지여야 한다"
    files = []
    for root in roots:
        for dirpath, _dirs, names in os.walk(root):
            files += [os.path.join(dirpath, n) for n in names if n.endswith(".py")]
    assert files
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            text = fh.read().lower()
        assert "sqlite3" not in text, f"{f} 에 sqlite3 가 있다"


def test_error_is_exception_subclass():
    assert issubclass(minisql.Error, Exception)


def test_connections_are_independent():
    a = minisql.connect()
    b = minisql.connect()
    a.execute("CREATE TABLE t (x INTEGER)")
    a.execute("INSERT INTO t VALUES (1)")
    b.execute("CREATE TABLE t (y TEXT)")
    assert a.execute("SELECT * FROM t").fetchall() == [(1,)]
    assert b.execute("SELECT * FROM t").fetchall() == []


def test_fetchone_fetchall_and_iteration():
    s, m = connections(EMP)
    sql = "SELECT id, name FROM emp ORDER BY id"
    cs, cm = s.execute(sql), m.execute(sql)
    assert cm.fetchone() == cs.fetchone()
    assert cm.fetchone() == cs.fetchone()
    assert cm.fetchall() == cs.fetchall()
    assert cm.fetchone() is None and cm.fetchall() == []
    cs, cm = s.execute(sql), m.execute(sql)
    cs.fetchone(), cm.fetchone()
    assert list(cm) == list(cs)


def test_description_and_rowcount_for_select():
    s, m = connections(EMP)
    sql = "SELECT id AS ident, name FROM emp WHERE 0"
    cs, cm = s.execute(sql), m.execute(sql)
    assert [d[0] for d in cm.description] == [d[0] for d in cs.description] == ["ident", "name"]
    assert len(cm.description[0]) == 7
    assert cm.fetchall() == []
    assert cm.rowcount == cs.rowcount == -1


def test_description_none_and_rowcount_for_create():
    m = minisql.connect()
    cur = m.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    assert cur.description is None
    assert cur.rowcount == -1


def test_rowcount_insert_update_delete():
    check_dml(EMP, [
        "INSERT INTO emp (id, name) VALUES (8, 'h'), (9, 'i'), (10, 'j')",
        "UPDATE emp SET salary = salary WHERE dept = 'eng'",
        "UPDATE emp SET bonus = 1.5 WHERE id > 100",
        "DELETE FROM emp WHERE salary IS NULL",
        "DELETE FROM emp",
    ], "SELECT count(*) FROM emp")


def test_results_are_int_not_bool():
    m = minisql.connect()
    row = m.execute("SELECT 1 < 2, 2 < 1, 1 = 1, NOT 0, 1 AND 1, 0 OR 0, 2 IN (1, 2), 'a' LIKE 'A'").fetchone()
    assert row == (1, 0, 1, 1, 1, 0, 1, 1)
    assert all(type(v) is int for v in row)


def test_parameters_types():
    check([], "SELECT ?, ?, ?, ?, typeof(?), typeof(?), ? + ?", (1, 2.5, "x", None, 3, "3", 2, "3"))


def test_parameter_in_where_gets_column_affinity():
    check(EMP, "SELECT name FROM emp WHERE id = ? OR salary = ?", ("2", "90.0"))


def test_parameter_in_insert_and_limit():
    check_dml(EMP, ["INSERT INTO emp (id, name, salary) VALUES (?, ?, ?)"],
              "SELECT id, name, salary, typeof(salary) FROM emp WHERE id = 20",
              params_list=[(20, "zed", "55")])
    check(EMP, "SELECT id FROM emp ORDER BY id LIMIT ? OFFSET ?", (2, 3), ordered=True)


def test_wrong_number_of_parameters():
    check_error(EMP, "SELECT * FROM emp WHERE id = ?", (1, 2))
    check_error(EMP, "SELECT * FROM emp WHERE id = ? AND name = ?", (1,))


def test_trailing_semicolon_and_comments():
    check(EMP, "SELECT id -- the id\n, /* block\ncomment */ name FROM emp WHERE id < 3 ; ")


def test_two_statements_in_execute_is_error():
    m = minisql.connect()
    with pytest.raises(minisql.Error):
        m.execute("CREATE TABLE t (a INTEGER); CREATE TABLE u (b INTEGER)")


def test_executescript():
    script = """
        CREATE TABLE t (a INTEGER, b TEXT);  -- first ; comment
        INSERT INTO t VALUES (1, 'x;y'), (2, 'it''s; fine');
        /* ; inside a comment */
        INSERT INTO t VALUES ('3', 4);
    """
    m = minisql.connect()
    m.executescript(script)
    s = sqlite3.connect(":memory:")
    s.executescript(script)
    sql = "SELECT a, typeof(a), b, typeof(b) FROM t ORDER BY a"
    assert m.execute(sql).fetchall() == s.execute(sql).fetchall()
