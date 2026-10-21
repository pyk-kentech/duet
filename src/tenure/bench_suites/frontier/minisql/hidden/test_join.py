"""Joins."""

import pytest

from sqlcheck import EMP, check, check_error

USING = [
    "CREATE TABLE a (id INTEGER, x TEXT)",
    "CREATE TABLE b (id INTEGER, y TEXT)",
    "CREATE TABLE c (id INTEGER, z TEXT)",
    "INSERT INTO a VALUES (1, 'p'), (2, 'q'), (3, NULL)",
    "INSERT INTO b VALUES (1, 'P'), (1, 'PP'), (4, 'Z'), (NULL, 'N')",
    "INSERT INTO c VALUES (1, 'c1'), (4, 'c4')",
    "CREATE TABLE empty_t (id INTEGER, w TEXT)",
]

JOIN_CASES = {
    "inner_join_on": "SELECT e.name, d.title FROM emp e JOIN dept d ON e.dept = d.code",
    "inner_keyword": "SELECT e.name, d.title FROM emp e INNER JOIN dept d ON d.code = e.dept AND d.floor > 1",
    "comma_join_with_where": "SELECT e.name, p.pname FROM emp e, proj p WHERE p.emp_id = e.id",
    "cross_join_count": "SELECT count(*) FROM emp CROSS JOIN dept",
    "join_without_on_is_cross": "SELECT count(*), sum(d.floor) FROM emp JOIN dept d",
    "left_join_no_match_gives_nulls": "SELECT d.code, e.name FROM dept d LEFT JOIN emp e ON e.dept = d.code",
    "left_outer_keyword": "SELECT e.name, p.pname, p.hours FROM emp e LEFT OUTER JOIN proj p ON p.emp_id = e.id",
    "left_join_condition_in_on": "SELECT e.name, p.pname FROM emp e LEFT JOIN proj p ON p.emp_id = e.id AND p.hours > 5",
    "left_join_condition_in_where": "SELECT e.name, p.pname FROM emp e LEFT JOIN proj p ON p.emp_id = e.id WHERE p.hours > 5",
    "left_join_anti_join": "SELECT e.name FROM emp e LEFT JOIN proj p ON p.emp_id = e.id WHERE p.pid IS NULL",
    "left_join_null_key_never_matches": "SELECT e.name, d.title FROM emp e LEFT JOIN dept d ON d.code = e.dept WHERE e.dept IS NULL OR d.floor IS NULL",
    "join_chain_inner_then_left": "SELECT e.name, d.title, p.pname FROM emp e JOIN dept d ON d.code = e.dept LEFT JOIN proj p ON p.emp_id = e.id",
    "join_chain_left_then_inner": "SELECT e.name, p.pname, d.title FROM emp e LEFT JOIN proj p ON p.emp_id = e.id JOIN dept d ON d.code = e.dept",
    "self_join": "SELECT w.name, m.name FROM emp w JOIN emp m ON w.manager = m.id",
    "self_left_join": "SELECT w.name, m.name FROM emp w LEFT JOIN emp m ON w.manager = m.id",
    "join_on_expression": "SELECT a.name, b.name FROM emp a JOIN emp b ON a.salary = b.salary + 20",
    "join_with_group_by": "SELECT d.title, count(e.id), avg(e.salary) FROM dept d LEFT JOIN emp e ON e.dept = d.code GROUP BY d.title",
    "three_way_comma_join": "SELECT e.name, d.floor, p.pname FROM emp e, dept d, proj p WHERE e.dept = d.code AND p.emp_id = e.id AND d.floor >= 1",
}


@pytest.mark.parametrize("sql", list(JOIN_CASES.values()), ids=list(JOIN_CASES))
def test_join(sql):
    check(EMP, sql)


USING_CASES = {
    "using_star_hides_right_column": "SELECT * FROM a JOIN b USING (id)",
    "using_left_join_star": "SELECT * FROM a LEFT JOIN b USING (id)",
    "using_unqualified_is_left_column": "SELECT id, x, y FROM a LEFT JOIN b USING (id)",
    "using_qualified_right_column": "SELECT a.id, b.id FROM a LEFT JOIN b USING (id)",
    "using_right_star_keeps_column": "SELECT b.* FROM a JOIN b USING (id)",
    "using_chain": "SELECT * FROM a JOIN b USING (id) JOIN c USING (id)",
    "left_join_empty_table": "SELECT a.id, empty_t.w FROM a LEFT JOIN empty_t ON empty_t.id = a.id",
    "inner_join_empty_table": "SELECT count(*) FROM a JOIN empty_t ON 1",
    "null_keys_do_not_join": "SELECT a.id, b.y FROM a JOIN b ON a.id = b.id OR (a.id IS NULL AND b.id IS NULL)",
}


@pytest.mark.parametrize("sql", list(USING_CASES.values()), ids=list(USING_CASES))
def test_join_using_and_edges(sql):
    check(USING, sql, names=True)


@pytest.mark.parametrize("sql", [
    "SELECT id FROM a JOIN b ON a.id = b.id",
    "SELECT x FROM a, a",
    "SELECT q.id FROM a",
    "SELECT a.id FROM a AS t",
    "SELECT z.* FROM a",
    "SELECT * FROM a JOIN nosuch ON 1",
    "SELECT a.nosuch FROM a JOIN b ON a.id = b.id",
])
def test_join_errors(sql):
    check_error(USING, sql)


def test_ambiguous_error_even_when_empty():
    check_error(USING, "SELECT id FROM empty_t JOIN a ON a.id = empty_t.id WHERE 0")
