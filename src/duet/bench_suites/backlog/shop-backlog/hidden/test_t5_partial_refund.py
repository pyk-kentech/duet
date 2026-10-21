"""티켓 5: 부분 환불은 쿠폰 할인을 반영해 수량 비례로 나눈다."""

import os
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal as D

from shop import Shop
from shop import reports, storage

T0 = datetime(2026, 3, 1, 12, 0)
DAY = date(2026, 3, 1)


def make_shop():
    s = Shop(clock=lambda: T0)
    s.add_product("BOOK", "Python Book", "books", "30.00", weight_g=800)
    s.add_product("MUG", "Mug", "home", "8.50", weight_g=350)
    s.add_product("LAMP", "Lamp", "home", "10.00", weight_g=1500)
    for sku in ("BOOK", "MUG", "LAMP"):
        s.receive(sku, 100)
    return s


def lamp_order(s=None, ship=True):
    """LAMP 3 x 10.00, 할인 5.00 -> N 25.00, T 4.75, 배송 7.90 (+1.50), 합계 39.15."""
    s = s or make_shop()
    s.add_coupon("FIVE", "fixed", "5")
    o = s.checkout([("LAMP", 3)], "Kim", coupons=["FIVE"])
    s.pay(o.id)
    if ship:
        s.ship(o.id)
    assert (o.lines[0].net, o.lines[0].tax, o.shipping, o.shipping_tax, o.total) == \
        (D("25.00"), D("4.75"), D("7.90"), D("1.50"), D("39.15"))
    return s, o


def parts(r):
    return (r.net, r.tax, r.shipping, r.amount)


def test_three_single_refunds():
    s, o = lamp_order()
    got = [parts(s.refund(o.id, {"LAMP": 1})) for _ in range(3)]
    assert got == [(D("8.33"), D("1.58"), 0, D("9.91")),
                   (D("8.34"), D("1.59"), 0, D("9.93")),
                   (D("8.33"), D("1.58"), 0, D("9.91"))]


def test_pieces_sum_to_line_and_keep_shipping():
    s, o = lamp_order()
    total = sum(s.refund(o.id, {"LAMP": 1}).amount for _ in range(3))
    assert total == D("29.75") and o.status == "refunded"
    assert sum(r.shipping for r in s.refunds_for(o.id)) == 0


def test_two_units_at_once():
    s, o = lamp_order()
    assert parts(s.refund(o.id, {"LAMP": 2})) == (D("16.67"), D("3.17"), 0, D("19.84"))


def test_full_refund_after_partial():
    s, o = lamp_order()
    first = s.refund(o.id, {"LAMP": 1})
    rest = s.refund(o.id)
    assert parts(rest) == (D("16.67"), D("4.67"), D("7.90"), D("29.24"))
    assert first.amount + rest.amount == o.total and o.status == "refunded"


def test_percent_coupon_allocation_refund():
    s = make_shop()
    s.add_coupon("SAVE10", "percent", "10")
    o = s.checkout([("BOOK", 1), ("MUG", 2)], "Kim", coupons=["SAVE10"])
    s.pay(o.id)
    s.ship(o.id)
    assert (o.lines[1].net, o.lines[1].tax) == (D("15.30"), D("2.91"))
    assert parts(s.refund(o.id, {"MUG": 1})) == (D("7.65"), D("1.46"), 0, D("9.11"))
    assert parts(s.refund(o.id, {"MUG": 1})) == (D("7.65"), D("1.45"), 0, D("9.10"))


def test_refund_before_ship_same_amounts():
    s, o = lamp_order(ship=False)
    r = s.refund(o.id, {"LAMP": 1})
    assert parts(r) == (D("8.33"), D("1.58"), 0, D("9.91"))
    assert s.inventory.reserved == {"LAMP": 2}


def test_category_report_subtracts_actual_refund():
    s, o = lamp_order()
    s.refund(o.id, {"LAMP": 1})
    assert reports.sales_by_category(s, DAY, DAY) == {"home": D("16.67")}


def test_tax_report_subtracts_actual_refund():
    s, o = lamp_order()
    s.refund(o.id, {"LAMP": 1})
    assert reports.tax_report(s, DAY, DAY) == [(D("19"), D("24.57"), D("4.67"))]


def test_full_refund_nets_to_zero_in_reports():
    s, o = lamp_order()
    s.refund(o.id, {"LAMP": 1})
    s.refund(o.id)
    assert reports.tax_report(s, DAY, DAY) == [(D("19"), D("0.00"), D("0.00"))]
    assert reports.sales_by_category(s, DAY, DAY) == {"home": D("0.00")}
    d = reports.daily_sales(s, DAY)
    assert (d.orders, d.net, d.tax) == (1, D("0.00"), D("0.00"))


def test_daily_report_consistent_with_refunds():
    s, o = lamp_order()
    r = s.refund(o.id, {"LAMP": 2})
    d = reports.daily_sales(s, DAY)
    assert (d.gross, d.refunds, d.net, d.tax) == (D("39.15"), D("19.84"), D("19.31"), D("3.08"))
    assert r.tax == D("3.17")


def test_cli_refund_amounts(tmp_path):
    s, o = lamp_order()
    data = tmp_path / "shop.json"
    storage.save(s, data)
    env = dict(os.environ, SHOP_NOW="2026-03-02T12:00:00", PYTHONIOENCODING="utf-8")

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "shop", "--data", str(data), *args], capture_output=True,
                              text=True, encoding="utf-8", env=env, timeout=60)

    assert cli("refund", str(o.id), "LAMP:1").stdout.strip() == "환불 1: 9.91"
    assert cli("refund", str(o.id), "LAMP:1").stdout.strip() == "환불 2: 9.93"
    assert cli("report", "category", "2026-03-01", "2026-03-01").stdout.splitlines() == ["home\t8.33"]
