"""CREATE / INSERT / UPDATE / DELETE."""

import sqlite3

import pytest

import minisql
from sqlcheck import EMP, check_dml, check_error, connections

ALL_EMP = "SELECT id, name, dept, salary, bonus, manager FROM emp"


def test_insert_column_list_order_and_missing_columns():
    check_dml(EMP, ["INSERT INTO emp (name, id) VALUES ('zed', 30)", "INSERT INTO emp (salary, dept, id) VALUES ('80', 7, 31)"],
              ALL_EMP + " WHERE id >= 30")


def test_insert_multi_row_with_expressions():
    check_dml(EMP, ["INSERT INTO emp VALUES (40, 'a' || 'b', upper('x'), 10 * 3, 1.5 + 1, NULL), (41, 'c', NULL, -5, '2.5', '1')"],
              ALL_EMP + " WHERE id >= 40")


def test_insert_with_scalar_subquery():
    check_dml(EMP, ["INSERT INTO emp (id, name, salary) VALUES ((SELECT max(id) + 1 FROM emp), 'new', (SELECT min(salary) FROM emp))"],
              ALL_EMP)


def test_insert_select():
    check_dml(EMP, ["CREATE TABLE rich (who TEXT, pay REAL)",
                    "INSERT INTO rich SELECT name, salary FROM emp WHERE salary >= 100",
                    "INSERT INTO rich (who) SELECT title FROM dept WHERE floor IS NULL"],
              "SELECT who, pay, typeof(pay) FROM rich")


def test_insert_select_from_same_table_reads_old_content():
    check_dml(EMP, ["INSERT INTO emp SELECT id + 100, name, dept, salary, bonus, manager FROM emp"],
              "SELECT count(*), max(id), sum(salary) FROM emp")


def test_insert_select_with_union_and_order():
    check_dml(EMP, ["CREATE TABLE names (n TEXT)",
                    "INSERT INTO names SELECT name FROM emp WHERE id < 3 UNION SELECT title FROM dept ORDER BY 1 LIMIT 4"],
              "SELECT n FROM names")


def test_update_uses_old_values():
    check_dml(EMP, ["UPDATE emp SET salary = bonus, bonus = salary WHERE dept = 'eng'"], ALL_EMP)


def test_update_expression_and_where():
    check_dml(EMP, ["UPDATE emp SET salary = salary + 10, name = upper(name) WHERE salary < 100 OR salary IS NULL"], ALL_EMP)


def test_update_all_rows_and_null():
    check_dml(EMP, ["UPDATE emp SET manager = NULL, dept = coalesce(dept, 'none')"], ALL_EMP)


def test_update_where_with_subquery_on_same_table():
    check_dml(EMP, ["UPDATE emp SET salary = salary * 2 WHERE salary < (SELECT avg(salary) FROM emp)"], ALL_EMP)


def test_update_with_correlated_subquery_from_other_table():
    check_dml(EMP, ["UPDATE emp SET bonus = (SELECT sum(hours) FROM proj WHERE proj.emp_id = emp.id) WHERE dept = 'eng'"], ALL_EMP)


def test_update_qualified_column_in_where():
    check_dml(EMP, ["UPDATE emp SET dept = 'ops' WHERE emp.id IN (SELECT emp_id FROM proj WHERE pname = 'zeus')"], ALL_EMP)


def test_update_no_matching_rows():
    check_dml(EMP, ["UPDATE emp SET salary = 0 WHERE name = 'nobody'"], ALL_EMP)


def test_delete_with_where():
    check_dml(EMP, ["DELETE FROM emp WHERE bonus IS NULL OR bonus < 3"], ALL_EMP)


def test_delete_where_subquery_on_same_table():
    check_dml(EMP, ["DELETE FROM emp WHERE salary > (SELECT avg(salary) FROM emp)"], ALL_EMP)


def test_delete_correlated_not_exists():
    check_dml(EMP, ["DELETE FROM proj WHERE NOT EXISTS (SELECT 1 FROM emp WHERE emp.id = proj.emp_id)"],
              "SELECT pid, emp_id, pname, hours FROM proj")


def test_delete_all_then_insert():
    check_dml(EMP, ["DELETE FROM dept", "INSERT INTO dept VALUES ('x', 'X', 1)"], "SELECT * FROM dept")


def test_where_three_valued_logic_in_delete():
    check_dml(EMP, ["DELETE FROM emp WHERE NOT (salary > 80)"], ALL_EMP)


def test_case_insensitive_table_and_column_names_in_dml():
    check_dml(EMP, ["INSERT INTO EMP (ID, Name) VALUES (50, 'up')", "UPDATE Emp SET SALARY = 1 WHERE NAME = 'up'",
                    "DELETE FROM eMp WHERE Id = 1"], ALL_EMP)


@pytest.mark.parametrize("sql", [
    "CREATE TABLE emp (x INTEGER)",
    "CREATE TABLE dup (a INTEGER, A TEXT)",
    "INSERT INTO emp VALUES (1, 'x')",
    "INSERT INTO emp (id, name) VALUES (1)",
    "INSERT INTO emp (id, nosuch) VALUES (1, 2)",
    "INSERT INTO dept VALUES ('a', 'b', 1), ('c', 'd')",
    "INSERT INTO dept SELECT code, title FROM dept",
    "INSERT INTO dept VALUES (code, 'x', 1)",
    "INSERT INTO nosuch VALUES (1)",
    "UPDATE emp SET nosuch = 1",
    "UPDATE emp SET salary = nosuch",
    "UPDATE nosuch SET a = 1",
    "DELETE FROM nosuch",
    "DELETE FROM emp WHERE nosuch = 1",
])
def test_dml_errors(sql):
    check_error(EMP, sql)


def test_failed_statement_changes_nothing():
    s, m = connections(EMP)
    for sql in ["INSERT INTO dept VALUES ('a', 'b', 1), ('c', 'd')",
                "UPDATE emp SET salary = 0, nosuch = 1",
                "INSERT INTO emp (id, name) SELECT pid, pname, hours FROM proj",
                "DELETE FROM emp WHERE nosuch(id)"]:
        with pytest.raises(sqlite3.Error):
            s.execute(sql)
        with pytest.raises(minisql.Error):
            m.execute(sql).fetchall()
    for q in ["SELECT count(*), sum(salary) FROM emp", "SELECT count(*) FROM dept"]:
        assert m.execute(q).fetchall() == s.execute(q).fetchall()


def test_errors_on_empty_table():
    setup = ["CREATE TABLE t (a INTEGER, b TEXT)"]
    check_error(setup, "SELECT c FROM t")
    check_error(setup, "SELECT a FROM t WHERE c = 1")
    check_error(setup, "UPDATE t SET b = c")
    check_error(setup, "DELETE FROM t WHERE c > 0")
