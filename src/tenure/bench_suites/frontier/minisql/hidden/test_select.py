"""SELECT: ORDER BY, LIMIT/OFFSET, DISTINCT, aliases and name resolution."""

import pytest

from sqlcheck import EMP, MIX, check, check_error

ORDER_CASES = {
    "nulls_first_in_asc": "SELECT name, salary FROM emp ORDER BY salary, id",
    "nulls_last_in_desc": "SELECT name, salary FROM emp ORDER BY salary DESC, id",
    "nulls_last_explicit": "SELECT name, salary FROM emp ORDER BY salary NULLS LAST, id",
    "nulls_first_desc_explicit": "SELECT name, salary FROM emp ORDER BY salary DESC NULLS FIRST, id DESC",
    "asc_nulls_first_keyword": "SELECT name FROM emp ORDER BY dept ASC NULLS FIRST, name",
    "multiple_keys_mixed": "SELECT dept, salary, name FROM emp ORDER BY dept DESC, salary ASC, name",
    "text_is_case_sensitive": "SELECT name FROM emp ORDER BY name",
    "mixed_types": "SELECT id, v FROM mix ORDER BY v, id",
    "mixed_types_desc": "SELECT id, v FROM mix ORDER BY v DESC, id",
    "ordinal": "SELECT name, salary FROM emp ORDER BY 2 DESC, 1",
    "alias": "SELECT name, salary * 2 AS dbl FROM emp ORDER BY dbl, name",
    "alias_case_insensitive": "SELECT name AS Who FROM emp ORDER BY wHO DESC",
    "alias_wins_over_column": "SELECT name AS salary, salary AS name FROM emp ORDER BY salary",
    "column_wins_inside_expression": "SELECT name AS salary, id FROM emp ORDER BY salary + 0, id",
    "expression_not_selected": "SELECT name FROM emp ORDER BY length(name) DESC, name",
    "column_not_selected": "SELECT name FROM emp ORDER BY manager DESC NULLS LAST, id",
    "case_expression": "SELECT name FROM emp ORDER BY CASE WHEN dept = 'eng' THEN 0 ELSE 1 END, name",
    "quoted_alias": 'SELECT name AS "Full Name" FROM emp ORDER BY "full name"',
}


@pytest.mark.parametrize("sql", list(ORDER_CASES.values()), ids=list(ORDER_CASES))
def test_order_by(sql):
    check(EMP + MIX, sql, ordered=True)


LIMIT_CASES = {
    "limit_offset": "SELECT id FROM emp ORDER BY id LIMIT 2 OFFSET 3",
    "limit_comma_form_offset_first": "SELECT id FROM emp ORDER BY id LIMIT 1, 3",
    "negative_limit_is_unlimited": "SELECT id FROM emp ORDER BY id LIMIT -1 OFFSET 5",
    "negative_offset_is_zero": "SELECT id FROM emp ORDER BY id LIMIT 2 OFFSET -3",
    "limit_zero": "SELECT id FROM emp ORDER BY id LIMIT 0",
    "limit_larger_than_rows": "SELECT id FROM emp ORDER BY id DESC LIMIT 100",
    "offset_past_end": "SELECT id FROM emp ORDER BY id LIMIT 3 OFFSET 50",
    "limit_expression": "SELECT id FROM emp ORDER BY id LIMIT 1 + 1 OFFSET 2 * 2",
    "limit_after_order_desc": "SELECT name FROM emp ORDER BY salary DESC NULLS LAST, id LIMIT 3",
}


@pytest.mark.parametrize("sql", list(LIMIT_CASES.values()), ids=list(LIMIT_CASES))
def test_limit(sql):
    check(EMP, sql, ordered=True)


DISTINCT_CASES = {
    "distinct_with_null": "SELECT DISTINCT dept FROM emp",
    "distinct_multi_column": "SELECT DISTINCT dept, salary FROM emp",
    "distinct_expression": "SELECT DISTINCT salary / 50 FROM emp",
    "distinct_one_and_one_point_zero": "SELECT count(*) FROM (SELECT DISTINCT v FROM (SELECT 1 AS v UNION ALL SELECT 1.0 UNION ALL SELECT '1' UNION ALL SELECT NULL UNION ALL SELECT NULL))",
    "distinct_text_case": "SELECT DISTINCT v FROM mix WHERE typeof(v) = 'text'",
    "select_all_keyword": "SELECT ALL dept FROM emp",
}


@pytest.mark.parametrize("sql", list(DISTINCT_CASES.values()), ids=list(DISTINCT_CASES))
def test_distinct(sql):
    check(EMP + MIX, sql)


def test_distinct_then_order_and_limit():
    check(EMP, "SELECT DISTINCT dept FROM emp ORDER BY dept DESC LIMIT 2", ordered=True)


ALIAS_CASES = {
    "alias_in_where": "SELECT name, salary * 2 AS dbl FROM emp WHERE dbl > 200",
    "column_wins_over_alias_in_where": "SELECT name AS dept FROM emp WHERE dept = 'eng'",
    "alias_in_group_by": "SELECT length(name) AS len, count(*) FROM emp GROUP BY len",
    "column_wins_over_alias_in_group_by": "SELECT count(*) AS n, min(salary) AS dept FROM emp GROUP BY dept",
    "alias_in_having": "SELECT dept, count(*) AS cnt FROM emp GROUP BY dept HAVING cnt > 1",
    "column_wins_over_alias_in_having": "SELECT dept AS salary, count(*) FROM emp GROUP BY dept HAVING max(salary) > 100",
    "implicit_alias_without_as": "SELECT name n, salary s FROM emp WHERE s > 95",
    "quoted_identifiers": 'SELECT "name", "Dept" FROM "emp" WHERE "ID" < 3',
    "case_insensitive_names": "SELECT NAME, Emp.Salary FROM EMP WHERE DEPT = 'eng'",
    "table_alias": "SELECT e.name FROM emp AS e WHERE e.salary > 100",
    "table_alias_without_as": "SELECT e.name FROM emp e WHERE e.id = 1",
    "star_and_qualified_star": "SELECT d.*, * FROM dept d WHERE floor IS NOT NULL",
}


@pytest.mark.parametrize("sql", list(ALIAS_CASES.values()), ids=list(ALIAS_CASES))
def test_aliases_and_names(sql):
    check(EMP, sql)


@pytest.mark.parametrize("sql", [
    "SELECT name AS x, x || '!' FROM emp",
    "SELECT emp.name FROM emp AS e",
    "SELECT nosuch FROM emp",
    "SELECT name FROM emp ORDER BY nosuch",
    "SELECT name FROM emp ORDER BY 3",
    "SELECT name FROM emp ORDER BY 0",
    "SELECT dept, count(*) FROM emp GROUP BY 5",
    "SELECT *",
])
def test_name_errors(sql):
    check_error(EMP, sql)


def test_select_without_from():
    check([], "SELECT 1 + 1, 'a' || 'b', NULL, 2.5 * 2")
