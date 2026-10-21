"""Result column names (cursor.description)."""

import pytest

from sqlcheck import EMP, check

NAME_CASES = {
    "expression_text_as_written": "SELECT id+1, id  +  1, COUNT( * ), count(*) FROM emp",
    "literals_and_parameter": ("SELECT 1, 'a', -1, NULL, 2.50, ?, 'it''s'", (7,)),
    "column_refs_use_declared_name": "SELECT NAME, E.SALARY, e.Dept FROM emp E",
    "parenthesized": "SELECT (id), ((name)), (id + 1) FROM emp",
    "aliases": 'SELECT id AS Ident, name n, salary "Pay Rate", bonus AS "x y" FROM emp',
    "star_join_duplicates": "SELECT * FROM emp JOIN dept ON dept.code = emp.dept",
    "qualified_star": "SELECT d.*, e.id FROM emp e JOIN dept d ON d.code = e.dept",
    "functions_and_case": "SELECT upper(name), name || '!' , CASE WHEN id > 1 THEN 'x' END FROM emp",
    "subqueries": "SELECT (SELECT max(id) FROM emp), EXISTS (SELECT 1), id IN (1, 2) FROM emp",
    "aggregates": "SELECT count(DISTINCT dept), sum(salary)/count(*), Max(bonus) FROM emp",
    "aggregate_query_column_ref": "SELECT DEPT, count(*) FROM emp GROUP BY dept",
    "from_subquery_alias": "SELECT x, S.y FROM (SELECT name AS x, id AS y FROM emp) S",
    "from_subquery_expression_name": "SELECT * FROM (SELECT id + 1, name FROM emp)",
    "cast": "SELECT CAST(salary AS TEXT), cast( id as real ) FROM emp",
    "no_rows_still_named": "SELECT name, salary * 2 FROM emp WHERE 0",
    "unary": "SELECT -salary, - salary, +id, NOT id FROM emp",
    "multiline_and_comment": "SELECT salary\n     + 1, 1 /* c */ + 2 FROM emp",
    "distinct": "SELECT DISTINCT Dept FROM emp",
    "using_column": "SELECT code, title FROM dept JOIN (SELECT dept AS code, count(*) AS n FROM emp GROUP BY dept) USING (code)",
}


@pytest.mark.parametrize("case", list(NAME_CASES.values()), ids=list(NAME_CASES))
def test_column_names(case):
    if isinstance(case, tuple):
        sql, params = case
    else:
        sql, params = case, ()
    check(EMP, sql, params, names=True)
