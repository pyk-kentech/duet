"""Subqueries (scalar, IN, EXISTS, correlated, FROM) and compound SELECTs."""

import pytest

from sqlcheck import EMP, check, check_error

SUB_CASES = {
    "scalar_in_select_list": "SELECT name, salary - (SELECT avg(salary) FROM emp) FROM emp",
    "scalar_no_rows_is_null": "SELECT name, (SELECT title FROM dept WHERE code = 'nope') FROM emp WHERE id < 3",
    "scalar_first_row_by_order": "SELECT (SELECT name FROM emp ORDER BY salary DESC), (SELECT name FROM emp ORDER BY salary)",
    "correlated_scalar": "SELECT e.name, (SELECT count(*) FROM proj p WHERE p.emp_id = e.id) FROM emp e",
    "correlated_scalar_with_limit": "SELECT e.name, (SELECT p.pname FROM proj p WHERE p.emp_id = e.id ORDER BY p.hours DESC LIMIT 1) FROM emp e",
    "correlated_compare_to_group_average": "SELECT name FROM emp e WHERE salary > (SELECT avg(salary) FROM emp e2 WHERE e2.dept = e.dept)",
    "in_subquery": "SELECT name FROM emp WHERE id IN (SELECT emp_id FROM proj WHERE pname = 'apollo')",
    "not_in_subquery": "SELECT name FROM emp WHERE id NOT IN (SELECT emp_id FROM proj)",
    "not_in_subquery_with_null_is_empty": "SELECT name FROM emp WHERE id NOT IN (SELECT manager FROM emp)",
    "in_subquery_with_null_value": "SELECT name, manager IN (SELECT manager FROM emp WHERE id > 5) FROM emp",
    "in_empty_subquery": "SELECT name, salary IN (SELECT 1 WHERE 0), salary NOT IN (SELECT 1 WHERE 0) FROM emp",
    "null_in_empty_subquery": "SELECT NULL IN (SELECT 1 WHERE 0), NULL NOT IN (SELECT 1 WHERE 0), NULL IN (SELECT 1)",
    "exists_correlated": "SELECT d.title FROM dept d WHERE EXISTS (SELECT 1 FROM emp e WHERE e.dept = d.code AND e.salary > 95)",
    "not_exists_correlated": "SELECT d.title FROM dept d WHERE NOT EXISTS (SELECT * FROM emp e WHERE e.dept = d.code)",
    "exists_is_never_null": "SELECT EXISTS (SELECT NULL), EXISTS (SELECT 1 WHERE 0), NOT EXISTS (SELECT 1 WHERE NULL)",
    "correlated_in_select_and_where": "SELECT name FROM emp e WHERE (SELECT count(*) FROM emp w WHERE w.manager = e.id) >= 2",
    "two_level_correlation": "SELECT d.code FROM dept d WHERE EXISTS (SELECT 1 FROM emp e WHERE e.dept = d.code AND EXISTS (SELECT 1 FROM proj p WHERE p.emp_id = e.id AND p.hours > d.floor * 2))",
    "subquery_in_having": "SELECT dept, count(*) FROM emp GROUP BY dept HAVING count(*) > (SELECT count(*) FROM dept WHERE floor = 1)",
    "subquery_in_order_by": "SELECT name FROM emp ORDER BY (SELECT count(*) FROM proj p WHERE p.emp_id = emp.id) DESC, id",
    "subquery_in_case": "SELECT name, CASE WHEN id IN (SELECT emp_id FROM proj) THEN 'busy' ELSE 'free' END FROM emp",
    "from_subquery": "SELECT s.dept, s.n FROM (SELECT dept, count(*) AS n FROM emp GROUP BY dept) AS s WHERE s.n > 1",
    "from_subquery_without_alias": "SELECT * FROM (SELECT name, salary * 2 AS dbl FROM emp WHERE salary > 95) WHERE dbl < 300",
    "aggregate_over_from_subquery": "SELECT avg(n), max(n) FROM (SELECT count(*) AS n FROM proj GROUP BY emp_id)",
    "from_subquery_joined": "SELECT e.name, t.total FROM emp e JOIN (SELECT emp_id, sum(hours) AS total FROM proj GROUP BY emp_id) t ON t.emp_id = e.id",
    "from_subquery_with_limit": "SELECT name FROM (SELECT name, salary FROM emp ORDER BY salary DESC NULLS LAST, id LIMIT 3) WHERE salary < 150",
}


@pytest.mark.parametrize("sql", list(SUB_CASES.values()), ids=list(SUB_CASES))
def test_subquery(sql):
    check(EMP, sql, ordered="ORDER BY name" in sql or sql.endswith("DESC, id"))


def test_from_subquery_column_names():
    check(EMP, "SELECT * FROM (SELECT id, name AS who, salary + 1, upper(dept) FROM emp WHERE id = 1)", names=True)


COMPOUND = EMP + [
    "CREATE TABLE t1 (a INTEGER, b TEXT)",
    "CREATE TABLE t2 (c INTEGER, d TEXT)",
    "INSERT INTO t1 VALUES (1, 'x'), (2, 'y'), (2, 'y'), (NULL, 'z'), (3, NULL)",
    "INSERT INTO t2 VALUES (2, 'y'), (NULL, 'z'), (4, 'w'), (4, 'w')",
]

COMPOUND_CASES = {
    "union_removes_duplicates_and_nulls_equal": "SELECT a, b FROM t1 UNION SELECT c, d FROM t2",
    "union_all_keeps_duplicates": "SELECT a, b FROM t1 UNION ALL SELECT c, d FROM t2",
    "intersect": "SELECT a, b FROM t1 INTERSECT SELECT c, d FROM t2",
    "except": "SELECT a, b FROM t1 EXCEPT SELECT c, d FROM t2",
    "except_dedupes_left": "SELECT b FROM t1 EXCEPT SELECT 'x'",
    "left_to_right_precedence": "SELECT a FROM t1 UNION SELECT c FROM t2 EXCEPT SELECT 2",
    "left_to_right_precedence_2": "SELECT a FROM t1 EXCEPT SELECT 2 UNION SELECT c FROM t2",
    "union_of_literals": "SELECT 1 UNION SELECT 2 UNION ALL SELECT 1",
    "compound_in_subquery": "SELECT name FROM emp WHERE id IN (SELECT a FROM t1 UNION SELECT c FROM t2)",
    "compound_in_from": "SELECT count(*), sum(v) FROM (SELECT a AS v FROM t1 UNION ALL SELECT c FROM t2)",
}


@pytest.mark.parametrize("sql", list(COMPOUND_CASES.values()), ids=list(COMPOUND_CASES))
def test_compound(sql):
    check(COMPOUND, sql)


COMPOUND_ORDER_CASES = {
    "order_by_ordinal": "SELECT a, b FROM t1 UNION SELECT c, d FROM t2 ORDER BY 1 DESC, 2",
    "order_by_first_select_name": "SELECT a, b FROM t1 UNION SELECT c, d FROM t2 ORDER BY b NULLS LAST, a",
    "order_by_alias_and_limit": "SELECT a AS k FROM t1 UNION ALL SELECT c FROM t2 ORDER BY k DESC NULLS LAST LIMIT 3",
    "limit_offset_on_compound": "SELECT a FROM t1 UNION SELECT c FROM t2 ORDER BY a LIMIT 2 OFFSET 1",
}


@pytest.mark.parametrize("sql", list(COMPOUND_ORDER_CASES.values()), ids=list(COMPOUND_ORDER_CASES))
def test_compound_order(sql):
    check(COMPOUND, sql, ordered=True)


def test_compound_column_names_from_first_select():
    check(COMPOUND, "SELECT a AS first, b FROM t1 UNION SELECT c, d AS ignored FROM t2", names=True)


@pytest.mark.parametrize("sql", [
    "SELECT a, b FROM t1 UNION SELECT c FROM t2",
    "SELECT a FROM t1 ORDER BY a UNION SELECT c FROM t2",
    "SELECT a FROM t1 UNION SELECT c FROM t2 ORDER BY 2",
    "SELECT name FROM emp WHERE id IN (SELECT a, b FROM t1)",
    "SELECT (SELECT a, b FROM t1)",
])
def test_subquery_errors(sql):
    check_error(COMPOUND, sql)
