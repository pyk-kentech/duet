from datetime import date, timedelta
from decimal import Decimal as D

from shop import reports
from shop.customers import customer_summary

DAY = date(2026, 3, 1)


def _two_paid(shop):
    a = shop.checkout([("BOOK", 1), ("MUG", 2)], "Kim")
    b = shop.checkout([("TEA", 10)], "Lee")
    for o in (a, b):
        shop.pay(o.id)
    return a, b


def test_daily_sales(shop):
    a, b = _two_paid(shop)
    r = reports.daily_sales(shop, DAY)
    assert (r.orders, r.gross, r.refunds) == (2, a.total + b.total, 0)
    assert r.net == r.gross and r.tax == a.tax + b.tax
    assert reports.daily_sales(shop, DAY + timedelta(days=1)).orders == 0


def test_daily_sales_with_refund(shop):
    a, b = _two_paid(shop)
    shop.ship(a.id)
    refund = shop.refund(a.id, {"MUG": 1})
    r = reports.daily_sales(shop, DAY)
    assert r.refunds == refund.amount and r.net == a.total + b.total - refund.amount


def test_sales_by_category(shop):
    _two_paid(shop)
    assert reports.sales_by_category(shop, DAY, DAY) == {"books": D("30.00"), "food": D("39.90"), "home": D("17.00")}


def test_top_products(shop):
    _two_paid(shop)
    assert reports.top_products(shop) == [("TEA", "Green Tea", 10), ("MUG", "Mug", 2), ("BOOK", "Python Book", 1)]
    assert reports.top_products(shop, n=1) == [("TEA", "Green Tea", 10)]


def test_tax_report(shop):
    _two_paid(shop)
    assert reports.tax_report(shop, DAY, DAY) == [
        (D("7"), D("69.90"), D("4.89")),
        (D("19"), D("26.80"), D("5.09")),
    ]


def test_cancelled_orders_excluded(shop):
    a, b = _two_paid(shop)
    shop.cancel(b.id)
    assert reports.daily_sales(shop, DAY).orders == 1
    assert "food" not in reports.sales_by_category(shop, DAY, DAY)
    assert [t[0] for t in reports.top_products(shop)] == ["MUG", "BOOK"]


def test_customer_summary_groups_names(shop):
    a = shop.checkout([("BOOK", 1)], "Kim  Min")
    b = shop.checkout([("MUG", 1)], " kim min ")
    for o in (a, b):
        shop.pay(o.id)
    (row,) = customer_summary(shop)
    assert row.customer == "Kim  Min" and row.orders == 2 and row.spent == a.total + b.total
