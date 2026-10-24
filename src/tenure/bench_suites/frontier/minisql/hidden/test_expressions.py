"""Operators, literals, three-valued logic, IN, BETWEEN, LIKE, CASE, CAST (mostly SELECT without FROM)."""

import pytest

from sqlcheck import EMP, MIX, check

EXPR_CASES = {
    "int_division": "SELECT 7/2, -7/2, 7/-2, -7/-2, 1/3, 0/5",
    "real_division": "SELECT 7/2.0, 7.0/2, -7/2.0, 1/4.0, typeof(4/2.0)",
    "int_modulo_signs": "SELECT 7%3, -7%3, 7%-3, -7%-3, 6%3",
    "real_modulo_truncates": "SELECT 5.5 % 2, -7.5 % 2, 5 % 2.5, 7.9 % 3.9, typeof(6 % 2.0)",
    "division_by_zero_is_null": "SELECT 1/0, 1%0, 1.0/0, 1/0.0, 5 % 0.5, 0/0, NULL/0",
    "text_in_arithmetic": "SELECT '3'+4, '3.5'+1, 'abc'+1, '12abc'+1, ' 7 '*2, '1.5kg'*2, '3.0'+1, typeof('3.0'+1), '2.5e1'+0, ''+1",
    "unary_minus_plus": "SELECT -'3', -'abc', -'1.5', +'abc', typeof(+'5'), -NULL, - -3, -(2-5), +NULL",
    "null_in_arithmetic": "SELECT NULL+1, 1-NULL, NULL*NULL, 2 % NULL",
    "concat": "SELECT 1.0||'x', 2.50||'', 100.0||'', 5||2, NULL||'a', 'a'||NULL, 0.25||'', -3.75||'', 1e2||'', 'a'||1||2.5",
    "precedence_comparison_levels": "SELECT 1 = 2 < 3, 0 = 1 > 2, 2 > 1 = 1, 1 < 2 <> 0",
    "precedence_concat_binds_tight": "SELECT 2 + 3 || 'x', 1 || 2 * 3, -1 || 'a', 10 - 2 || 1",
    "precedence_arith": "SELECT 1 + 2 * 3 - 4 / 2, (1 + 2) * 3, 10 - 2 - 3, 2 * 3 % 4, 20 / 2 / 5, 7 - -2",
    "precedence_not": "SELECT NOT 1 = 2, NOT 0 AND 0, NOT (0 AND 0), 1 OR 0 AND 0, (1 OR 0) AND 0",
    "compare_literals_no_affinity": "SELECT '5' = 5, 5 = '5', '10' < '9', 'a' < 1, 'a' > 99, 1 = 1.0, 'B' < 'a', '' > 0, 'abc' = 'ABC'",
    "compare_null": "SELECT NULL = NULL, NULL <> 1, 1 < NULL, NULL >= NULL, NULL == 1",
    "is_operator": "SELECT NULL IS NULL, 1 IS NULL, NULL IS NOT NULL, 1 IS 1.0, '1' IS 1, 2 IS NOT 3, NULL IS 0, 0 IS NOT NULL",
    "three_valued_and_or": "SELECT NULL AND 0, NULL AND 1, NULL OR 1, NULL OR 0, 0 AND NULL, 1 OR NULL, NULL AND NULL, NULL OR NULL",
    "three_valued_not": "SELECT NOT NULL, NOT 0, NOT 5, NOT NOT 7, NOT -1, NOT (NULL = 1)",
    "truthiness_of_text": "SELECT 'abc' AND 1, '1abc' OR 0, NOT 'abc', NOT '0', NOT '2x', 2.5 AND 1, CASE WHEN 'abc' THEN 1 ELSE 0 END",
    "in_list": "SELECT 1 IN (1, 2), 3 IN (1, 2), 1 IN (1, NULL), 3 IN (1, NULL), 3 NOT IN (1, NULL), 1 NOT IN (2, 3)",
    "in_null_and_empty": "SELECT NULL IN (1), NULL NOT IN (1), NULL IN (), NULL NOT IN (), 1 IN (), 1 NOT IN ()",
    "in_list_types": "SELECT '1' IN (1), 1 IN ('1'), 1 IN (1.0), 'a' IN ('A', 'a'), 2 IN (1+1, 3)",
    "between": "SELECT 5 BETWEEN 1 AND 10, 5 BETWEEN 10 AND 1, NULL BETWEEN 1 AND 2, 5 NOT BETWEEN 1 AND 4, 'b' BETWEEN 'a' AND 'c', 3 BETWEEN 3 AND 3",
    "between_with_null_bounds": "SELECT 1 BETWEEN NULL AND 0, 3 BETWEEN 1 AND NULL, 3 NOT BETWEEN 1 AND NULL, 0 NOT BETWEEN NULL AND -1",
    "between_precedence": "SELECT 1 BETWEEN 0 AND 2 = 1, 5 BETWEEN 1 + 1 AND 2 * 3, 2 BETWEEN 1 AND 3 AND 0",
    "like_basic": "SELECT 'abc' LIKE 'ABC', 'abc' LIKE 'a%', 'abc' LIKE 'a_c', 'ac' LIKE 'a_c', 'abc' LIKE 'b%', '' LIKE '%', 'a' LIKE '', 'abc' LIKE '%C'",
    "like_non_ascii_case": "SELECT 'é' LIKE 'É', 'É' LIKE 'É', 'Straße' LIKE 'STRASSE', 'xÿz' LIKE 'x_z'",
    "like_numbers_and_null": "SELECT 12 LIKE '1%', 2.0 LIKE '2.0', 2.5 LIKE '2._', NULL LIKE 'a', 'a' LIKE NULL, 'ab' NOT LIKE 'a', NULL NOT LIKE 'a'",
    "like_newline_and_wildcards": "SELECT 'a\nb' LIKE 'a_b', 'a\nb' LIKE 'a%', 'a%b' LIKE 'a%b', '_' LIKE '__'",
    "like_escape": "SELECT '10%' LIKE '10!%' ESCAPE '!', '100' LIKE '10!%' ESCAPE '!', 'a_b' LIKE 'a!_b' ESCAPE '!', 'axb' LIKE 'a!_b' ESCAPE '!', 'a!b' LIKE 'a!!b' ESCAPE '!'",
    "case_simple": "SELECT CASE 1 WHEN 1 THEN 'a' WHEN 2 THEN 'b' END, CASE 3 WHEN 1 THEN 'a' END, CASE 2 WHEN 1 THEN 'a' WHEN 2 THEN 'b' ELSE 'c' END",
    "case_null_and_types": "SELECT CASE NULL WHEN NULL THEN 'x' ELSE 'y' END, CASE 1.0 WHEN 1 THEN 'eq' END, CASE '1' WHEN 1 THEN 'eq' ELSE 'ne' END",
    "case_searched": "SELECT CASE WHEN NULL THEN 1 WHEN 0 THEN 2 ELSE 3 END, CASE WHEN 1 > 2 THEN 'x' END, CASE WHEN 2 > 1 THEN 'y' WHEN 1 THEN 'z' END",
    "cast_integer": "SELECT CAST('12.7' AS INTEGER), CAST('abc' AS INTEGER), CAST(' 42abc' AS INTEGER), CAST('-3.9' AS INTEGER), CAST(-2.7 AS INTEGER), CAST(2.7 AS INT), CAST('+8' AS BIGINT)",
    "cast_real": "SELECT CAST('1.5abc' AS REAL), CAST('abc' AS REAL), CAST(3 AS REAL), typeof(CAST(3 AS REAL)), CAST(' 2.5 ' AS DOUBLE), CAST('12' AS FLOAT)",
    "cast_text": "SELECT CAST(2.5 AS TEXT), CAST(5 AS TEXT), CAST(1.0 AS TEXT), CAST(5 AS VARCHAR(3)), typeof(CAST(5 AS VARCHAR(3))), CAST(-0.25 AS TEXT)",
    "cast_numeric": "SELECT CAST('42' AS NUMERIC), CAST('3.5' AS NUMERIC), CAST('abc' AS NUMERIC), CAST('3.0' AS NUMERIC), CAST(3.0 AS NUMERIC), CAST('12abc' AS NUMERIC), typeof(CAST('3.0' AS DECIMAL(5,2)))",
    "cast_null": "SELECT CAST(NULL AS INTEGER), typeof(CAST(NULL AS TEXT)), CAST(NULL AS REAL)",
    "typeof_results": "SELECT typeof(1), typeof(1.0), typeof(1e2), typeof('a'), typeof(NULL), typeof(1/2), typeof(1/2.0), typeof(1 < 2), typeof('1' + 1), typeof('1.0' + 1), typeof('a' || 1)",
    "literal_forms": "SELECT .5 + 0, 2. + 0, 1e3, 1E-2, 'it''s', 'a\\b', length('a\\b'), typeof(10), -0 + 0",
    "keywords_case_insensitive": "select Null Is nUlL, 3 bEtWeEn 1 AnD 5, 'A' LiKe 'a', CaSe WhEn 1 ThEn 'y' EnD",
}


@pytest.mark.parametrize("sql", list(EXPR_CASES.values()), ids=list(EXPR_CASES))
def test_expression(sql):
    check([], sql)


def test_where_without_from():
    check([], "SELECT 1 WHERE 0")
    check([], "SELECT 'yes' WHERE NULL IS NULL")
    check([], "SELECT 1 WHERE NULL")


TABLE_CASES = {
    "where_null_comparisons": "SELECT name FROM emp WHERE salary != 100",
    "where_not_with_null": "SELECT name FROM emp WHERE NOT (salary > 90)",
    "where_or_with_null": "SELECT name FROM emp WHERE salary > 110 OR dept = 'hr'",
    "where_and_with_null": "SELECT name FROM emp WHERE NOT (dept = 'eng' AND salary > 110)",
    "where_is_null": "SELECT name FROM emp WHERE dept IS NULL OR bonus IS NULL",
    "where_is_not_value": "SELECT name FROM emp WHERE dept IS NOT 'eng'",
    "where_text_truthiness": "SELECT id FROM mix WHERE v",
    "where_numeric_column_truthiness": "SELECT name FROM emp WHERE bonus",
    "where_between_columns": "SELECT name FROM emp WHERE bonus BETWEEN 1 AND salary / 10",
    "where_like_column": "SELECT name FROM emp WHERE name LIKE '%a%' AND name NOT LIKE 'D%'",
    "where_in_with_null_column": "SELECT name FROM emp WHERE manager NOT IN (2, 3)",
    "select_expressions_on_columns": "SELECT id, salary / 3, salary % 7, bonus * 2, salary / 40.0, name || '/' || dept FROM emp",
    "case_on_columns": "SELECT name, CASE WHEN salary >= 100 THEN 'high' WHEN salary >= 80 THEN 'mid' ELSE 'low' END FROM emp",
    "case_simple_on_column": "SELECT name, CASE dept WHEN 'eng' THEN 1 WHEN 'hr' THEN 2 END FROM emp",
    "mixed_type_comparisons": "SELECT id, v > 2, v < 'B', v = 10, v IS NULL FROM mix",
}


@pytest.mark.parametrize("sql", list(TABLE_CASES.values()), ids=list(TABLE_CASES))
def test_expression_on_tables(sql):
    check(EMP + MIX, sql)
