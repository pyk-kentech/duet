"""Scalar functions."""

import pytest

from sqlcheck import EMP, check, check_error

FUNC_CASES = {
    "abs": "SELECT abs(-5), abs(-2.5), abs(3), abs(NULL), typeof(abs(-5)), typeof(abs(-2.5))",
    "abs_text": "SELECT abs('-5'), abs('abc'), abs('-2.5x'), typeof(abs('-5'))",
    "length": "SELECT length('héllo'), length(12), length(-1.5), length(2.0), length(NULL), length(''), length(100.0)",
    "upper_lower_ascii_only": "SELECT upper('é abc'), lower('ÀBC'), upper('straße'), lower('MiXeD 1')",
    "upper_lower_non_text": "SELECT upper(1.5), typeof(upper(5)), lower(NULL), upper(10)",
    "substr_positive": "SELECT substr('abcde', 2), substr('abcde', 2, 2), substr('abcde', 1, 10), substr('abcde', 10), substr('abcde', 5, 1)",
    "substr_negative_start": "SELECT substr('abcde', -2), substr('abcde', -2, 1), substr('abcde', -10, 3), substr('abcde', -10, 7), substr('abcde', -5, 2)",
    "substr_negative_length": "SELECT substr('abcde', 3, -2), substr('abcde', 1, -1), substr('abcde', -3, -1), substr('abcde', 4, -10), substr('abcde', 5, -5)",
    "substr_conversions": "SELECT substr(12345, 2, 3), substr('abcde', 2.7, 1.9), substr('abcde', '2', '2'), substr('héllo', 2, 2), substr(1.5, 2)",
    "substr_null": "SELECT substr('abcde', NULL), substr(NULL, 1), substr('abc', 1, NULL)",
    "trim_default_spaces_only": "SELECT trim('  a b  '), trim(' \tabc\n '), ltrim('  ab  '), rtrim('  ab  ')",
    "trim_with_chars": "SELECT trim('xxaxx', 'x'), trim('abcba', 'ab'), ltrim('aab', 'a'), rtrim(12300, '0'), trim('abc', ''), rtrim('a.b..', '.')",
    "trim_null": "SELECT trim(NULL), trim('abc', NULL), ltrim(NULL, 'a')",
    "replace": "SELECT replace('abcabc', 'b', 'X'), replace('aaa', 'aa', 'b'), replace(12321, 2, 9), replace('abc', 'B', 'x'), replace('a.b.c', '.', '')",
    "replace_empty_and_null": "SELECT replace('abc', '', 'X'), replace(5, '', 1), typeof(replace(5, '', 1)), replace('abc', NULL, 'x'), replace('abc', 'b', NULL), replace('abc', '', NULL), replace(NULL, 'a', 'b')",
    "instr": "SELECT instr('abcabc', 'ca'), instr('abc', ''), instr('abc', 'z'), instr(12345, 34), instr(NULL, 'a'), instr('héllo', 'l'), instr('abc', 'C'), instr('abc', NULL)",
    "round_half_away_from_zero": "SELECT round(2.5), round(-2.5), round(0.5), round(1.5), round(-0.5), round(3.5)",
    "round_digits": "SELECT round(0.125, 2), round(-0.125, 2), round(1.234, 2), round(1.5678, 1), round(0.375, 2), round(2.5, -1)",
    "round_types": "SELECT round(7), typeof(round(7)), round(-0.4), round('2.5'), round(NULL), round(2.5, NULL), typeof(round(7, 2))",
    "coalesce_ifnull": "SELECT coalesce(NULL, NULL, 3, 4), coalesce(NULL, 'a'), coalesce(NULL, NULL), ifnull(NULL, 2), ifnull(1, 2), typeof(coalesce(NULL, 2.0))",
    "nullif": "SELECT nullif(1, 1), nullif(1, 1.0), nullif('1', 1), nullif(NULL, 1), nullif(2, NULL), nullif('a', 'A'), nullif(3, 4)",
    "typeof": "SELECT typeof(NULL), typeof(-3), typeof(-3.0), typeof('x'), typeof(typeof(1)), typeof(CAST(1 AS TEXT))",
    "scalar_max_min": "SELECT max(1, 2, 3), min(3, 1, 2), min(2, 1.5), max(1, '0'), min('a', 'B'), typeof(max(1, 2.5)), min(3, 'x', 2), max('abc', 'abd')",
    "scalar_max_min_null": "SELECT max(1, NULL, 3), min(NULL, 1), max(NULL, NULL), min(1, 2, NULL)",
    "function_names_case_insensitive": "SELECT UPPER('a'), Length('abc'), TypeOf(1), COALESCE(NULL, 1), Abs(-1)",
    "nested_functions": "SELECT upper(substr(trim('  hello  '), 2, 3)), length(replace('a-b-c', '-', '')), round(abs(-2.5)) || '!'",
}


@pytest.mark.parametrize("sql", list(FUNC_CASES.values()), ids=list(FUNC_CASES))
def test_function(sql):
    check([], sql)


TABLE_CASES = {
    "functions_on_columns": "SELECT id, upper(name), length(name), substr(name, 2, 2), coalesce(dept, '-'), ifnull(bonus, 0) FROM emp",
    "functions_in_where": "SELECT name FROM emp WHERE lower(name) LIKE '%a%' AND length(name) <= 5",
    "scalar_max_over_columns": "SELECT id, max(salary, 100), min(bonus, 6), max(salary, bonus) FROM emp",
    "nullif_in_division": "SELECT id, salary / nullif(bonus, 0.0) FROM emp",
    "round_avg_like_expression": "SELECT id, round(salary / 7.0, 2), round(bonus) FROM emp",
}


@pytest.mark.parametrize("sql", list(TABLE_CASES.values()), ids=list(TABLE_CASES))
def test_function_on_tables(sql):
    check(EMP, sql)


@pytest.mark.parametrize("sql", [
    "SELECT nosuchfunc(1)",
    "SELECT abs(1, 2)",
    "SELECT coalesce(1)",
    "SELECT substr('a')",
    "SELECT round(1, 2, 3)",
    "SELECT length()",
])
def test_function_errors(sql):
    check_error([], sql)


def test_unknown_function_error_on_empty_table():
    check_error(["CREATE TABLE t (a INTEGER)"], "SELECT nosuchfunc(a) FROM t")
