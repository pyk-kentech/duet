"""Aggregates, GROUP BY, HAVING."""

import pytest

from sqlcheck import EMP, MIX, check, check_error

AGG_CASES = {
    "count_star_vs_count_column": "SELECT count(*), count(salary), count(bonus), count(dept) FROM emp",
    "count_distinct": "SELECT count(DISTINCT dept), count(DISTINCT salary), count(DISTINCT manager) FROM emp",
    "sum_types": "SELECT sum(salary), typeof(sum(salary)), sum(bonus), typeof(sum(bonus)) FROM emp",
    "sum_of_mixed_int_real_is_real": "SELECT sum(v), typeof(sum(v)) FROM mix WHERE typeof(v) IN ('integer', 'real')",
    "avg_is_real": "SELECT avg(salary), typeof(avg(salary)), avg(manager) FROM emp",
    "total_is_real": "SELECT total(salary), typeof(total(salary)), total(bonus) FROM emp",
    "min_max_skip_null": "SELECT min(salary), max(salary), min(bonus), max(bonus), min(dept), max(dept) FROM emp",
    "min_max_cross_type": "SELECT min(v), max(v), typeof(max(v)) FROM mix",
    "empty_input_one_row": "SELECT count(*), count(salary), sum(salary), total(salary), avg(salary), min(salary), max(name) FROM emp WHERE id > 100",
    "all_null_input": "SELECT count(bonus), sum(bonus), total(bonus), avg(bonus), max(bonus) FROM emp WHERE bonus IS NULL",
    "aggregate_arithmetic": "SELECT max(salary) - min(salary), sum(salary) / count(salary), sum(salary) / count(*), count(*) * 2 + 1 FROM emp",
    "sum_distinct_avg_distinct": "SELECT sum(DISTINCT salary), avg(DISTINCT salary), total(DISTINCT salary) FROM emp",
    "count_without_from": "SELECT count(*), sum(5), max('a')",
    "aggregate_of_expression": "SELECT sum(salary * 2), max(length(name)), min(salary / 40), avg(CASE WHEN bonus IS NULL THEN 0 ELSE 1 END) FROM emp",
    "aggregate_with_where": "SELECT count(*), sum(salary) FROM emp WHERE dept = 'eng'",
}


@pytest.mark.parametrize("sql", list(AGG_CASES.values()), ids=list(AGG_CASES))
def test_aggregate(sql):
    check(EMP + MIX, sql)


GROUP_CASES = {
    "group_with_null_key": "SELECT dept, count(*), sum(salary), avg(salary) FROM emp GROUP BY dept",
    "group_by_expression": "SELECT salary / 50, count(*) FROM emp GROUP BY salary / 50",
    "group_by_ordinal": "SELECT dept, max(salary) FROM emp GROUP BY 1",
    "group_by_two_columns": "SELECT dept, manager, count(*) FROM emp GROUP BY dept, manager",
    "group_by_typeof": "SELECT typeof(v), count(*), count(v) FROM mix GROUP BY typeof(v)",
    "group_one_and_one_point_zero_same_group": "SELECT count(*) FROM (SELECT x FROM (SELECT 1 AS x UNION ALL SELECT 1.0 UNION ALL SELECT '1' UNION ALL SELECT 2) GROUP BY x)",
    "group_by_on_empty_input": "SELECT dept, count(*) FROM emp WHERE id > 100 GROUP BY dept",
    "group_by_column_not_selected": "SELECT count(*), max(name) FROM emp GROUP BY dept",
    "having_with_aggregate_not_selected": "SELECT dept FROM emp GROUP BY dept HAVING sum(salary) > 150",
    "having_count": "SELECT dept, count(*) FROM emp GROUP BY dept HAVING count(*) >= 2",
    "having_on_group_column": "SELECT dept, count(*) FROM emp GROUP BY dept HAVING dept IS NOT NULL AND dept <> 'hr'",
    "having_with_null_aggregate": "SELECT dept, avg(bonus) FROM emp GROUP BY dept HAVING avg(bonus) > 1",
    "group_expressions_over_key": "SELECT upper(dept), count(*) * 10, dept || ':' || count(*) FROM emp GROUP BY dept",
    "count_on_left_join": "SELECT d.code, count(e.id), count(*) FROM dept d LEFT JOIN emp e ON e.dept = d.code GROUP BY d.code",
    "sum_on_left_join_is_null": "SELECT d.code, sum(e.salary), total(e.salary) FROM dept d LEFT JOIN emp e ON e.dept = d.code GROUP BY d.code",
    "group_concat_single_value_groups": "SELECT id, group_concat(name), group_concat(salary, '+') FROM emp GROUP BY id",
    "group_concat_skips_null_and_empty": "SELECT dept, group_concat(bonus), group_concat(NULL) FROM emp WHERE id IN (2, 5, 6) GROUP BY dept",
    "group_concat_length": "SELECT length(group_concat(name)), length(group_concat(name, '')), length(group_concat(id, ' - ')) FROM emp",
    "group_concat_same_values": "SELECT group_concat(dept) FROM emp WHERE dept = 'sales'",
    "group_concat_distinct_count": "SELECT length(group_concat(DISTINCT dept)) FROM emp",
}


@pytest.mark.parametrize("sql", list(GROUP_CASES.values()), ids=list(GROUP_CASES))
def test_group_by(sql):
    check(EMP + MIX, sql)


def test_order_by_aggregate():
    check(EMP, "SELECT dept, count(*) AS c FROM emp GROUP BY dept ORDER BY c DESC, dept", ordered=True)
    check(EMP, "SELECT dept FROM emp GROUP BY dept ORDER BY sum(salary) DESC NULLS LAST, dept", ordered=True)


def test_integer_average_trap():
    check(EMP, "SELECT dept, sum(salary) / count(salary), avg(salary) FROM emp WHERE salary IS NOT NULL GROUP BY dept")


@pytest.mark.parametrize("sql", [
    "SELECT name FROM emp WHERE count(*) > 1",
    "SELECT dept FROM emp GROUP BY count(*)",
    "SELECT dept FROM emp WHERE sum(salary) > 1 GROUP BY dept",
])
def test_aggregate_misuse_errors(sql):
    check_error(EMP, sql)
