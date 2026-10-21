"""티켓 4: 묶음 쿠폰 bundle (N+1)."""

import json
import os
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal as D

import pytest

from shop import CouponError, Shop, ValidationError
from shop import reports, storage

T0 = datetime(2026, 3, 1, 12, 0)
DAY = date(2026, 3, 1)


def make_shop():
    s = Shop(clock=lambda: T0)
    s.add_product("BOOK", "Python Book", "books", "30.00", weight_g=800)
    s.add_product("NOVEL", "Novel", "books", "12.00", weight_g=300)
    s.add_product("MUG", "Mug", "home", "8.50", weight_g=350)
    s.add_product("PEN", "Pen", "office", "0.99", weight_g=10, tiers="10:5")
    for sku in ("BOOK", "NOVEL", "MUG", "PEN"):
        s.receive(sku, 500)
    return s


def run_cli(data, *args):
    env = dict(os.environ, SHOP_NOW="2026-03-01T12:00:00", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "shop", "--data", str(data), *args], capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=60)


def discounts(order):
    return [ln.discount for ln in order.lines]


def test_bundle_per_line():
    s = make_shop()
    s.add_coupon("B21", "bundle", "2", category="books")
    o = s.checkout([("BOOK", 3), ("NOVEL", 7), ("MUG", 3)], "Kim", coupons=["B21"])
    assert discounts(o) == [D("30.00"), D("24.00"), D("0.00")]
    o = s.checkout([("BOOK", 2), ("NOVEL", 1)], "Kim", coupons=["B21"])     # 줄끼리 합치지 않는다
    assert discounts(o) == [D("0.00"), D("0.00")]


def test_bundle_one_plus_one():
    s = make_shop()
    s.add_coupon("B11", "bundle", "1", category="books")
    o = s.checkout([("NOVEL", 5)], "Kim", coupons=["B11"])
    assert discounts(o) == [D("24.00")]


def test_bundle_uses_tier_discounted_unit():
    s = make_shop()
    s.add_coupon("PENS", "bundle", "2", category="office")
    o = s.checkout([("PEN", 12)], "Kim", coupons=["PENS"])
    assert o.lines[0].unit_price == D("0.94") and discounts(o) == [D("3.76")]


def test_bundle_before_category_percent():
    s = make_shop()
    s.add_coupon("B21", "bundle", "2", category="books", stackable=True)
    s.add_coupon("BOOKS10", "category_percent", "10", category="books", stackable=True)
    o = s.checkout([("BOOK", 3)], "Kim", coupons=["BOOKS10", "B21"])
    assert discounts(o) == [D("36.00")]


def test_bundle_before_percent():
    s = make_shop()
    s.add_coupon("B21", "bundle", "2", category="books", stackable=True)
    s.add_coupon("SAVE10", "percent", "10", stackable=True)
    o = s.checkout([("BOOK", 3), ("MUG", 2)], "Kim", coupons=["SAVE10", "B21"])
    assert discounts(o) == [D("36.00"), D("1.70")]


def test_tax_on_discounted_amount():
    s = make_shop()
    s.add_coupon("B21", "bundle", "2", category="books")
    o = s.checkout([("BOOK", 3)], "Kim", coupons=["B21"])
    assert o.lines[0].net == D("60.00") and o.lines[0].tax == D("4.20")
    assert o.total == D("64.20")


def test_min_subtotal_and_free_shipping_use_pre_coupon_subtotal():
    s = make_shop()
    s.add_coupon("B21", "bundle", "2", category="books", min_subtotal="60")
    o = s.checkout([("NOVEL", 5)], "Kim", coupons=["B21"])        # 소계 60.00, 할인 12.00
    assert discounts(o) == [D("12.00")] and o.shipping == 0
    with pytest.raises(CouponError):
        s.checkout([("NOVEL", 4)], "Kim", coupons=["B21"])


def test_stacking_rules():
    s = make_shop()
    s.add_coupon("B21", "bundle", "2", category="books")
    s.add_coupon("SAVE10", "percent", "10", stackable=True)
    s.add_coupon("SHIP", "free_shipping")
    with pytest.raises(CouponError):
        s.checkout([("BOOK", 3)], "Kim", coupons=["B21", "SAVE10"])
    o = s.checkout([("NOVEL", 3)], "Kim", region="eu", coupons=["B21", "SHIP"])
    assert discounts(o) == [D("12.00")] and o.shipping == 0


def test_validation():
    s = make_shop()
    for value, category in [("2.5", "books"), ("0", "books"), ("-1", "books"), ("2", None)]:
        with pytest.raises(ValidationError):
            s.add_coupon("BAD", "bundle", value, category=category)
    assert s.add_coupon("B31", "bundle", "3", category="office").value == 3


def test_quote_matches_checkout():
    s = make_shop()
    s.add_coupon("B21", "bundle", "2", category="books")
    q = s.quote([("BOOK", 4), ("MUG", 1)], coupons=["B21"])
    o = s.checkout([("BOOK", 4), ("MUG", 1)], "Kim", coupons=["B21"])
    assert [x.discount for x in q.lines] == discounts(o) == [D("30.00"), D("0.00")]
    assert q.total == o.total


def test_storage_round_trip(tmp_path):
    s = make_shop()
    s.add_coupon("B21", "bundle", "2", category="books", max_uses=10)
    o = s.checkout([("BOOK", 3)], "Kim", coupons=["B21"])
    storage.save(s, tmp_path / "s.json")
    s2 = storage.load(tmp_path / "s.json")
    c = s2.coupon("B21")
    assert (c.kind, c.value, c.category, c.uses, c.max_uses) == ("bundle", D("2"), "books", 1, 10)
    assert s2.get_order(o.id).lines[0].discount == D("30.00")
    o2 = s2.checkout([("NOVEL", 3)], "Lee", coupons=["B21"])
    assert discounts(o2) == [D("12.00")]


def test_saved_file_contains_bundle_coupon(tmp_path):
    s = make_shop()
    s.add_coupon("B21", "bundle", "2", category="books", stackable=True)
    storage.save(s, tmp_path / "s.json")
    data = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    (c,) = data["coupons"]
    assert (c["code"], c["kind"], c["category"], c["stackable"]) == ("B21", "bundle", "books", True)
    assert D(str(c["value"])) == 2
    s2 = storage.load(tmp_path / "s.json")
    assert s2.quote([("NOVEL", 6)], coupons=["B21"]).discount == D("24.00")


def test_cli_coupon_add_and_list(tmp_path):
    data = tmp_path / "shop.json"
    storage.save(make_shop(), data)
    r = run_cli(data, "coupon-add", "b21", "bundle", "2", "--category", "books")
    assert r.returncode == 0, r.stderr
    assert run_cli(data, "coupons").stdout.splitlines() == ["B21\tbundle\t2+1\t0/-"]
    r = run_cli(data, "order", "BOOK:3", "--customer", "Kim", "--coupon", "B21")
    assert r.stdout.strip() == "주문 1001 생성 (합계 64.20)"
    assert run_cli(data, "coupons").stdout.splitlines() == ["B21\tbundle\t2+1\t1/-"]


def test_refund_of_bundle_line():
    s = make_shop()
    s.add_coupon("B21", "bundle", "2", category="books")
    o = s.checkout([("BOOK", 3)], "Kim", coupons=["B21"])
    s.pay(o.id)
    s.ship(o.id)
    r = s.refund(o.id, {"BOOK": 1})
    assert (r.net, r.tax, r.amount) == (D("20.00"), D("1.40"), D("21.40"))


def test_tax_and_category_reports_reflect_bundle():
    s = make_shop()
    s.add_coupon("B21", "bundle", "2", category="books")
    o = s.checkout([("BOOK", 3)], "Kim", coupons=["B21"])
    s.pay(o.id)
    assert reports.tax_report(s, DAY, DAY) == [(D("7"), D("60.00"), D("4.20"))]
    s.ship(o.id)
    s.refund(o.id, {"BOOK": 1})
    assert reports.tax_report(s, DAY, DAY) == [(D("7"), D("40.00"), D("2.80"))]
    assert reports.sales_by_category(s, DAY, DAY) == {"books": D("40.00")}
