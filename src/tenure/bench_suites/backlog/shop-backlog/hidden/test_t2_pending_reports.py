"""티켓 2: 결제 전(pending) 주문은 보고서에 넣지 않는다."""

import os
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal as D

from shop import Shop
from shop import reports, storage
from shop.customers import customer_summary

T0 = datetime(2026, 3, 1, 12, 0)
DAY = date(2026, 3, 1)


def make_shop():
    s = Shop(clock=lambda: T0)
    s.add_product("BOOK", "Python Book", "books", "30.00", weight_g=800)
    s.add_product("NOVEL", "Novel", "books", "12.00", weight_g=300)
    s.add_product("MUG", "Mug", "home", "8.50", weight_g=350)
    for sku in ("BOOK", "NOVEL", "MUG"):
        s.receive(sku, 100)
    return s


def scenario():
    """A(결제, 37.93), B(미결제, 26.06), C(결제, 31.51) — 모두 3월 1일."""
    s = make_shop()
    a = s.checkout([("BOOK", 1)], "Kim")
    b = s.checkout([("MUG", 2)], "Lee")
    c = s.checkout([("NOVEL", 2)], "Park")
    s.pay(a.id)
    s.pay(c.id)
    assert (a.total, b.total, c.total) == (D("37.93"), D("26.06"), D("31.51"))
    return s, a, b, c


def run_cli(data, *args):
    env = dict(os.environ, SHOP_NOW="2026-03-02T12:00:00", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "shop", "--data", str(data), *args], capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=60)


def test_daily_excludes_pending():
    s, a, b, c = scenario()
    r = reports.daily_sales(s, DAY)
    assert (r.orders, r.gross, r.refunds, r.net, r.tax) == (2, D("69.44"), 0, D("69.44"), D("5.64"))


def test_category_excludes_pending():
    s, a, b, c = scenario()
    assert reports.sales_by_category(s, DAY, DAY) == {"books": D("54.00")}


def test_top_products_excludes_pending():
    s, a, b, c = scenario()
    assert reports.top_products(s) == [("NOVEL", "Novel", 2), ("BOOK", "Python Book", 1)]


def test_tax_report_excludes_pending():
    s, a, b, c = scenario()
    assert reports.tax_report(s, DAY, DAY) == [(D("7"), D("54.00"), D("3.78")), (D("19"), D("9.80"), D("1.86"))]


def test_customer_summary_excludes_pending():
    s, a, b, c = scenario()
    rows = customer_summary(s)
    assert [(r.customer, r.orders, r.spent) for r in rows] == [("Kim", 1, D("37.93")), ("Park", 1, D("31.51"))]


def test_customer_with_paid_and_pending_orders():
    s, a, b, c = scenario()
    s.checkout([("BOOK", 2)], " kim ")                      # 같은 고객의 미결제 주문
    (kim,) = [r for r in customer_summary(s) if r.customer == "Kim"]
    assert (kim.orders, kim.spent, kim.first_order, kim.last_order) == (1, D("37.93"), DAY, DAY)


def test_customer_appears_after_payment():
    s, a, b, c = scenario()
    s.pay(b.id)
    rows = customer_summary(s)
    assert [(r.customer, r.orders, r.spent) for r in rows] == [("Kim", 1, D("37.93")), ("Park", 1, D("31.51")),
                                                                ("Lee", 1, D("26.06"))]


def test_paid_later_is_included_on_order_date():
    s, a, b, c = scenario()
    s.pay(b.id)
    r = reports.daily_sales(s, DAY)
    assert (r.orders, r.gross) == (3, D("95.50"))
    assert reports.sales_by_category(s, DAY, DAY) == {"books": D("54.00"), "home": D("17.00")}


def test_only_pending_gives_empty_reports():
    s = make_shop()
    s.checkout([("BOOK", 2)], "Kim")
    assert reports.daily_sales(s, DAY).orders == 0
    assert reports.sales_by_category(s, DAY, DAY) == {}
    assert reports.top_products(s) == []
    assert reports.tax_report(s, DAY, DAY) == []


def test_cli_report_daily(tmp_path):
    s, a, b, c = scenario()
    data = tmp_path / "shop.json"
    storage.save(s, data)
    out = run_cli(data, "report", "daily", "2026-03-01").stdout.splitlines()
    assert out == ["date\t2026-03-01", "orders\t2", "gross\t69.44", "refunds\t0.00", "net\t69.44", "tax\t5.64"]


def test_cli_report_top_and_category(tmp_path):
    s, a, b, c = scenario()
    data = tmp_path / "shop.json"
    storage.save(s, data)
    assert run_cli(data, "report", "top").stdout.splitlines() == ["NOVEL\tNovel\t2", "BOOK\tPython Book\t1"]
    assert run_cli(data, "report", "category", "2026-03-01", "2026-03-01").stdout.splitlines() == ["books\t54.00"]
    assert run_cli(data, "report", "tax", "2026-03-01", "2026-03-31").stdout.splitlines() == \
        ["7%\t54.00\t3.78", "19%\t9.80\t1.86"]


def test_cli_report_customers(tmp_path):
    s, a, b, c = scenario()
    data = tmp_path / "shop.json"
    storage.save(s, data)
    assert run_cli(data, "report", "customers").stdout.splitlines() == ["Kim\t1\t37.93\t0.00", "Park\t1\t31.51\t0.00"]
