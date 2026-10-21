"""A few hundred rows inserted with parameters, then ordinary queries (correctness, not speed)."""

import sqlite3

import pytest

import minisql
from sqlcheck import assert_rows

QUERIES = [
    ("SELECT grp, count(*), sum(qty), avg(price), min(tag), max(tag) FROM sales GROUP BY grp", False),
    ("SELECT id, qty * price FROM sales WHERE qty > 40 AND tag LIKE 't1%' ORDER BY qty * price DESC, id LIMIT 15", True),
    ("SELECT a.grp, count(*) FROM sales a JOIN sales b ON a.id = b.id + 7 AND a.grp = b.grp GROUP BY a.grp", False),
    ("SELECT tag, count(*) FROM sales GROUP BY tag HAVING count(*) > 20", False),
    ("SELECT count(DISTINCT qty), count(DISTINCT grp), total(price) FROM sales WHERE note IS NULL", False),
    ("SELECT id FROM sales WHERE qty IN (SELECT qty FROM sales WHERE grp = 'g3' AND price > 50) ORDER BY id LIMIT 20 OFFSET 5", True),
    ("SELECT grp, qty FROM sales s WHERE qty = (SELECT max(qty) FROM sales t WHERE t.grp = s.grp)", False),
]


def _fill(con):
    con.execute("CREATE TABLE sales (id INTEGER, grp TEXT, qty INTEGER, price REAL, tag TEXT, note)")
    for i in range(1, 301):
        grp = "g%d" % (i % 7)
        qty = (i * 37) % 61
        price = ((i * 53) % 997) / 8.0
        tag = "t%d" % (i % 13)
        note = None if i % 4 else ("n%d" % i if i % 8 else i)
        con.execute("INSERT INTO sales VALUES (?, ?, ?, ?, ?, ?)", (i, grp, str(qty) if i % 5 == 0 else qty, price, tag, note))


@pytest.mark.parametrize("sql,ordered", QUERIES, ids=[f"q{i}" for i in range(len(QUERIES))])
def test_bulk_query(sql, ordered):
    s = sqlite3.connect(":memory:")
    m = minisql.connect()
    _fill(s)
    _fill(m)
    assert_rows(s.execute(sql).fetchall(), m.execute(sql).fetchall(), ordered, sql)
