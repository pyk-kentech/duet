"""Realistic queries that combine several rules (joins across affinities, grouping, ordering, subqueries)."""

import pytest

from sqlcheck import check, check_dml

SHOP = [
    "CREATE TABLE customer (cid INTEGER, cname TEXT, city TEXT, tier)",
    "INSERT INTO customer VALUES (1, 'Ann', 'Seoul', 'gold'), (2, 'ben', 'Busan', NULL), (3, 'Cho', NULL, 'silver'), "
    "(4, 'dan', 'Seoul', 'gold'), (5, 'Eun', 'Daegu', 'bronze')",
    "CREATE TABLE orders (oid INTEGER, cid TEXT, amount REAL, qty INTEGER, status TEXT, placed TEXT)",
    "INSERT INTO orders VALUES (100, '1', 30.5, 2, 'paid', '2024-01-05'), (101, '1', 12, 1, 'paid', '2024-02-11'), "
    "(102, '2', NULL, 3, 'open', '2024-02-12'), (103, ' 3', 99.75, 1, 'paid', '2024-03-01'), "
    "(104, '9', 5, 10, 'void', '2024-03-02'), (105, '4', 45, '4', 'PAID', '2024-03-15'), "
    "(106, '4', 0, 0, 'open', NULL), (107, '1', 7.25, 3, 'paid', '2024-04-01')",
]

UNORDERED = {
    "left_join_like_in_on_and_total": "SELECT c.cname, count(o.oid), total(o.amount) FROM customer c LEFT JOIN orders o "
                                      "ON o.cid = c.cid AND o.status LIKE 'paid' GROUP BY c.cid, c.cname",
    "join_text_key_with_spaces": "SELECT c.cname, o.oid FROM customer c JOIN orders o ON o.cid = c.cid",
    "text_key_vs_literal_no_match": "SELECT oid FROM orders WHERE cid = 3 OR cid = 1",
    "in_subquery_across_affinities": "SELECT cname FROM customer WHERE cid IN (SELECT cid FROM orders WHERE status <> 'void')",
    "not_in_subquery_across_affinities": "SELECT cname FROM customer WHERE cid NOT IN (SELECT cid FROM orders WHERE status = 'paid')",
    "status_groups_are_case_sensitive": "SELECT status, count(*), sum(qty) FROM orders GROUP BY status",
    "group_by_alias_of_upper": "SELECT upper(status) AS s, sum(qty), max(amount) FROM orders GROUP BY s",
    "alias_in_where_with_real_math": "SELECT oid, amount * qty AS line FROM orders WHERE line > 40",
    "month_groups_with_null": "SELECT substr(placed, 1, 7) AS month, count(*), total(amount) FROM orders GROUP BY month",
    "derived_totals_joined": "SELECT c.cname, t.s FROM (SELECT cid, sum(amount) AS s FROM orders GROUP BY cid) t "
                             "JOIN customer c ON c.cid = t.cid WHERE t.s > 20",
    "except_has_no_affinity": "SELECT cid FROM customer EXCEPT SELECT cid FROM orders",
    "intersect_with_cast": "SELECT cid FROM customer INTERSECT SELECT CAST(cid AS INTEGER) FROM orders",
    "integer_percentages": "SELECT status, 100 * count(*) / (SELECT count(*) FROM orders), 100.0 * count(*) / (SELECT count(*) FROM orders) "
                           "FROM orders GROUP BY status",
    "avg_vs_sum_over_count": "SELECT avg(amount), sum(amount) / count(*), sum(amount) / count(amount), sum(qty) / count(*) FROM orders",
    "above_customer_average": "SELECT o.oid FROM orders o WHERE o.amount > (SELECT avg(o2.amount) FROM orders o2 WHERE o2.cid = o.cid)",
    "customers_without_orders": "SELECT c.cname FROM customer c LEFT JOIN orders o ON o.cid = c.cid WHERE o.oid IS NULL",
    "city_counts_with_length": "SELECT coalesce(city, '?'), count(*), length(group_concat(cname, '')) FROM customer GROUP BY city",
    "case_buckets_group_by_ordinal": "SELECT CASE WHEN amount IS NULL THEN 'none' WHEN amount BETWEEN 0 AND 10 THEN 'small' "
                                     "ELSE 'big' END AS bucket, count(*), sum(qty) FROM orders GROUP BY 1",
    "having_with_tier_and_count": "SELECT tier, count(*) FROM customer GROUP BY tier HAVING tier IS NOT NULL AND count(*) >= 1",
    "real_column_text_output": "SELECT oid, amount || ' x ' || qty, amount / 2, typeof(amount) FROM orders WHERE amount IS NOT NULL",
}


@pytest.mark.parametrize("sql", list(UNORDERED.values()), ids=list(UNORDERED))
def test_combined(sql):
    check(SHOP, sql)


ORDERED = {
    "revenue_ranking": "SELECT c.cname, total(o.amount) AS revenue FROM customer c LEFT JOIN orders o ON o.cid = c.cid "
                       "GROUP BY c.cid, c.cname ORDER BY revenue DESC, c.cname",
    "binary_name_rank": "SELECT cname, (SELECT count(*) FROM customer c2 WHERE c2.cname < c.cname) + 1 AS pos FROM customer c ORDER BY pos",
    "top_orders_nulls_last_comma_limit": "SELECT oid, amount FROM orders ORDER BY amount DESC NULLS LAST, oid LIMIT 1, 3",
    "union_cities_statuses": "SELECT city AS v FROM customer UNION SELECT status FROM orders ORDER BY v NULLS LAST LIMIT 5",
    "distinct_city_desc_nulls_first": "SELECT DISTINCT city FROM customer ORDER BY city DESC NULLS FIRST",
    "coalesce_order_nulls_first": "SELECT cname, coalesce(city, 'unknown') FROM customer ORDER BY city NULLS FIRST, cname",
}


@pytest.mark.parametrize("sql", list(ORDERED.values()), ids=list(ORDERED))
def test_combined_ordered(sql):
    check(SHOP, sql, ordered=True)


def test_update_with_in_subquery_across_affinities():
    check_dml(SHOP, ["UPDATE orders SET status = 'paid' WHERE status = 'open' AND cid IN (SELECT cid FROM customer WHERE tier = 'gold')"],
              "SELECT oid, status FROM orders")


def test_delete_orphans_with_correlated_not_exists():
    check_dml(SHOP, ["DELETE FROM orders WHERE NOT EXISTS (SELECT 1 FROM customer c WHERE c.cid = orders.cid)"],
              "SELECT oid FROM orders")


def test_insert_select_copy_then_aggregate():
    check_dml(SHOP, ["INSERT INTO orders SELECT oid + 100, cid, amount * 2, qty, 'copy', NULL FROM orders WHERE status IN ('void', 'open')"],
              "SELECT status, count(*), total(amount), sum(qty) FROM orders GROUP BY status")
