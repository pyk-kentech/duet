"""기존 동작 (보고서 규칙). 시작 코드와 바뀐 코드 모두에서 같아야 한다."""

from datetime import date, datetime, timedelta
from decimal import Decimal as D

from shop import Shop
from shop import reports
from shop.customers import customer_summary

T0 = datetime(2026, 3, 1, 12, 0)
DAY = date(2026, 3, 1)


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


def make_shop(clock=None):
    s = Shop(clock=clock or Clock())
    s.add_product("BOOK", "Python Book", "books", "30.00", weight_g=800)
    s.add_product("NOVEL", "Novel", "books", "12.00", weight_g=300)
    s.add_product("MUG", "Mug", "home", "8.50", weight_g=350)
    s.add_product("PEN", "Pen", "office", "0.99", weight_g=10)
    for sku in ("BOOK", "NOVEL", "MUG", "PEN"):
        s.receive(sku, 500)
    return s


def paid(s, items, customer="Kim", ship=False):
    o = s.checkout(items, customer)
    s.pay(o.id)
    if ship:
        s.ship(o.id)
    return o


def test_fully_refunded_order_still_counted_in_daily():
    s = make_shop()
    o = paid(s, [("BOOK", 1)], ship=True)
    s.refund(o.id)
    r = reports.daily_sales(s, DAY)
    assert (r.orders, r.gross, r.refunds, r.net, r.tax) == (1, D("37.93"), D("37.93"), D("0.00"), D("0.00"))


def test_fully_refunded_category_kept_at_zero():
    s = make_shop()
    o = paid(s, [("BOOK", 1)], ship=True)
    paid(s, [("MUG", 1)])
    s.refund(o.id)
    assert reports.sales_by_category(s, DAY, DAY) == {"books": D("0.00"), "home": D("8.50")}


def test_refunded_by_partials_keeps_shipping_in_reports():
    s = make_shop()
    o = paid(s, [("NOVEL", 2)], ship=True)
    s.refund(o.id, {"NOVEL": 1})
    s.refund(o.id, {"NOVEL": 1})
    assert o.status == "refunded"
    assert reports.tax_report(s, DAY, DAY) == [(D("7"), D("0.00"), D("0.00")), (D("19"), D("4.90"), D("0.93"))]
    r = reports.daily_sales(s, DAY)
    assert (r.orders, r.gross, r.refunds, r.net) == (1, D("31.51"), D("25.68"), D("5.83"))
    assert [(x.customer, x.orders, x.spent, x.refunded) for x in customer_summary(s)] == \
        [("Kim", 1, D("5.83"), D("25.68"))]


def test_cancelled_after_payment_excluded_everywhere():
    s = make_shop()
    paid(s, [("BOOK", 1)])
    b = paid(s, [("MUG", 1)], customer="Lee")
    s.cancel(b.id)
    assert reports.daily_sales(s, DAY).orders == 1
    assert reports.daily_sales(s, DAY).refunds == 0
    assert reports.sales_by_category(s, DAY, DAY) == {"books": D("30.00")}
    assert reports.top_products(s) == [("BOOK", "Python Book", 1)]
    assert reports.tax_report(s, DAY, DAY) == [(D("7"), D("30.00"), D("2.10")), (D("19"), D("4.90"), D("0.93"))]
    assert [x.customer for x in customer_summary(s)] == ["Kim"]


def test_refunds_counted_on_order_date():
    clock = Clock()
    s = make_shop(clock)
    o = paid(s, [("MUG", 2)], ship=True)
    clock.t = T0 + timedelta(days=4)
    r = s.refund(o.id, {"MUG": 1})
    assert reports.daily_sales(s, DAY).refunds == r.amount
    later = reports.daily_sales(s, date(2026, 3, 5))
    assert (later.orders, later.refunds) == (0, 0)
    assert reports.top_products(s, start=DAY, end=DAY) == [("MUG", "Mug", 1)]


def test_custom_rate_and_shipping_rows():
    s = make_shop()
    s.tax_table.set_rate("home", "7.5")
    paid(s, [("MUG", 2)])
    assert reports.tax_report(s, DAY, DAY) == [(D("7.5"), D("17.00"), D("1.28")), (D("19"), D("4.90"), D("0.93"))]


def test_top_products_order_ties_and_limit():
    s = make_shop()
    paid(s, [("BOOK", 2), ("MUG", 3)])
    paid(s, [("NOVEL", 2)])
    p = paid(s, [("PEN", 1)], ship=True)
    s.refund(p.id)
    assert reports.top_products(s, n=10) == [("MUG", "Mug", 3), ("BOOK", "Python Book", 2), ("NOVEL", "Novel", 2)]
    assert reports.top_products(s, n=2) == [("MUG", "Mug", 3), ("BOOK", "Python Book", 2)]


def test_date_ranges_inclusive():
    clock = Clock()
    s = make_shop(clock)
    paid(s, [("BOOK", 1)])
    clock.t = T0 + timedelta(days=2)
    paid(s, [("MUG", 1)])
    assert reports.sales_by_category(s, DAY, date(2026, 3, 3)) == {"books": D("30.00"), "home": D("8.50")}
    assert reports.sales_by_category(s, date(2026, 3, 2), date(2026, 3, 3)) == {"home": D("8.50")}
    assert reports.sales_by_category(s, date(2026, 3, 4), date(2026, 3, 9)) == {}
    assert reports.top_products(s, start=date(2026, 3, 3)) == [("MUG", "Mug", 1)]
    assert [row[0] for row in reports.tax_report(s, date(2026, 3, 2), date(2026, 3, 3))] == [D("19")]


def test_customer_summary_names_and_order():
    clock = Clock()
    s = make_shop(clock)
    a = paid(s, [("BOOK", 1)], customer="  Kim   Min ", ship=True)
    clock.t = T0 + timedelta(days=1)
    paid(s, [("MUG", 1)], customer="kim min")
    paid(s, [("NOVEL", 4)], customer="Choi")
    s.refund(a.id, {"BOOK": 1})
    rows = customer_summary(s)
    assert [(r.customer, r.orders, r.refunded, r.first_order, r.last_order) for r in rows] == [
        ("Choi", 1, D("0.00"), date(2026, 3, 2), date(2026, 3, 2)),
        ("Kim   Min", 2, D("32.10"), date(2026, 3, 1), date(2026, 3, 2)),
    ]
    assert rows[1].spent == a.total + D("15.95") - D("32.10")
