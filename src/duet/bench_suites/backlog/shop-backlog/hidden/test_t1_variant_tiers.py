"""티켓 1: 같은 상품의 변형은 수량 할인 구간을 합쳐서 정한다."""

import os
import subprocess
import sys
from datetime import datetime
from decimal import Decimal as D

import pytest

from shop import CouponError, Shop
from shop import storage

T0 = datetime(2026, 3, 1, 12, 0)


def make_shop():
    s = Shop(clock=lambda: T0)
    s.add_product("BOOK", "Python Book", "books", "30.00", weight_g=800)
    s.add_product("PEN", "Pen", "office", "0.99", weight_g=10, tiers="10:5")
    s.add_product("TSHIRT", "T-Shirt", "apparel", "19.99", weight_g=200, tiers="10:10")
    s.add_variant("TSHIRT", "TSHIRT-S", attrs={"size": "S"})
    s.add_variant("TSHIRT", "TSHIRT-L", attrs={"size": "L"}, price="24.99")
    s.add_product("CAP", "Cap", "apparel", "15.00", weight_g=100, tiers="10:20")
    s.add_variant("CAP", "CAP-RED", attrs={"color": "red"})
    s.add_variant("CAP", "CAP-BLUE", attrs={"color": "blue"})
    s.add_product("SOCK", "Sock", "apparel", "5.00", weight_g=50, tiers="10:10")
    s.add_variant("SOCK", "SOCK-W", attrs={"color": "white"})
    s.add_variant("SOCK", "SOCK-B", attrs={"color": "black"})
    for sku in ("BOOK", "PEN", "TSHIRT-S", "TSHIRT-L", "CAP-RED", "CAP-BLUE", "SOCK-W", "SOCK-B"):
        s.receive(sku, 500)
    return s


def units(lines):
    return [(ln.sku, ln.qty, ln.unit_price) for ln in lines]


def run_cli(data, *args):
    env = dict(os.environ, SHOP_NOW="2026-03-01T12:00:00", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "shop", "--data", str(data), *args], capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=60)


def test_checkout_variants_share_tier():
    o = make_shop().checkout([("TSHIRT-S", 5), ("TSHIRT-L", 5)], "Kim")
    assert units(o.lines) == [("TSHIRT-S", 5, D("17.99")), ("TSHIRT-L", 5, D("22.49"))]
    assert [ln.list_price for ln in o.lines] == [D("19.99"), D("24.99")]


def test_checkout_tier_not_over_applied():
    s = make_shop()
    o = s.checkout([("TSHIRT-S", 5), ("TSHIRT-L", 4)], "Kim")
    assert units(o.lines) == [("TSHIRT-S", 5, D("19.99")), ("TSHIRT-L", 4, D("24.99"))]
    o = s.checkout([("TSHIRT-S", 5), ("CAP-RED", 5), ("CAP-BLUE", 4)], "Kim")      # 다른 상품끼리는 안 합친다
    assert units(o.lines) == [("TSHIRT-S", 5, D("19.99")), ("CAP-RED", 5, D("15.00")), ("CAP-BLUE", 4, D("15.00"))]
    assert s.checkout([("PEN", 9), ("BOOK", 1)], "Kim").lines[0].unit_price == D("0.99")
    o = s.checkout([("PEN", 10)], "Kim")
    assert o.lines[0].unit_price == D("0.94") and o.subtotal == D("9.40")


def test_uneven_variant_split():
    o = make_shop().checkout([("CAP-RED", 1), ("CAP-BLUE", 9)], "Kim")
    assert units(o.lines) == [("CAP-RED", 1, D("12.00")), ("CAP-BLUE", 9, D("12.00"))]


def test_repeated_sku_merged_then_grouped():
    o = make_shop().checkout([("TSHIRT-S", 3), ("TSHIRT-L", 4), ("TSHIRT-S", 3)], "Kim")
    assert units(o.lines) == [("TSHIRT-S", 6, D("17.99")), ("TSHIRT-L", 4, D("22.49"))]


def test_totals_and_tax_use_grouped_prices():
    o = make_shop().checkout([("TSHIRT-S", 5), ("TSHIRT-L", 5)], "Kim")
    assert o.subtotal == D("202.40")
    assert [ln.tax for ln in o.lines] == [D("17.09"), D("21.37")]
    assert o.shipping == 0 and o.total == D("240.86")


def test_checkout_coupon_minimum_and_free_shipping_use_grouped_subtotal():
    s = make_shop()
    s.add_coupon("MIN210", "fixed", "5", min_subtotal="210")
    with pytest.raises(CouponError):
        s.checkout([("TSHIRT-S", 5), ("TSHIRT-L", 5)], "Kim", coupons=["MIN210"])
    o = s.checkout([("SOCK-W", 5), ("SOCK-B", 5)], "Kim")
    assert o.subtotal == D("45.00") and o.shipping == D("4.90")


def test_quote_uses_grouped_tier():
    q = make_shop().quote([("TSHIRT-S", 5), ("TSHIRT-L", 5)])
    assert [(x.sku, x.unit_price) for x in q.lines] == [("TSHIRT-S", D("17.99")), ("TSHIRT-L", D("22.49"))]
    assert q.total == D("240.86")


def test_quote_uneven_lines():
    q = make_shop().quote([("CAP-RED", 1), ("BOOK", 1), ("CAP-BLUE", 9)])
    assert [(x.sku, x.unit_price) for x in q.lines] == [("CAP-RED", D("12.00")), ("BOOK", D("30.00")),
                                                        ("CAP-BLUE", D("12.00"))]


def test_quote_equals_checkout_with_coupon():
    s = make_shop()
    s.add_coupon("SAVE10", "percent", "10")
    items = [("CAP-RED", 6), ("TSHIRT-S", 2), ("CAP-BLUE", 4), ("BOOK", 1)]
    q = s.quote(items, coupons=["SAVE10"])
    o = s.checkout(items, "Kim", coupons=["SAVE10"])
    assert [(x.sku, x.unit_price, x.discount, x.tax) for x in q.lines] ==            [(x.sku, x.unit_price, x.discount, x.tax) for x in o.lines]
    assert (q.subtotal, q.shipping, q.total) == (o.subtotal, o.shipping, o.total)
    assert o.lines[0].unit_price == D("12.00")


def test_quote_coupon_minimum_and_free_shipping_use_grouped_subtotal():
    s = make_shop()
    s.add_coupon("MIN210", "fixed", "5", min_subtotal="210")
    with pytest.raises(CouponError):
        s.quote([("TSHIRT-S", 5), ("TSHIRT-L", 5)], coupons=["MIN210"])
    q = s.quote([("SOCK-W", 5), ("SOCK-B", 5)])
    assert q.subtotal == D("45.00") and q.shipping == D("4.90")


def test_cli_quote(tmp_path):
    data = tmp_path / "shop.json"
    storage.save(make_shop(), data)
    r = run_cli(data, "quote", "TSHIRT-S:5", "TSHIRT-L:5")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["  TSHIRT-S  T-Shirt (S)  5 x 17.99 = 89.95",
                                     "  TSHIRT-L  T-Shirt (L)  5 x 22.49 = 112.45",
                                     "소계: 202.40", "배송: 0.00", "세금: 38.46", "합계: 240.86"]


def test_reprice_keeps_grouping():
    s = make_shop()
    o = s.checkout([("TSHIRT-S", 5), ("TSHIRT-L", 5)], "Kim")
    s.catalog.set_price("TSHIRT-L", "29.99")
    s.reprice(o.id)
    assert units(o.lines) == [("TSHIRT-S", 5, D("17.99")), ("TSHIRT-L", 5, D("26.99"))]


def test_reprice_after_product_price_change():
    s = make_shop()
    o = s.checkout([("CAP-RED", 4), ("CAP-BLUE", 6)], "Kim")
    s.catalog.set_price("CAP", "20.00")
    s.reprice(o.id)
    assert units(o.lines) == [("CAP-RED", 4, D("16.00")), ("CAP-BLUE", 6, D("16.00"))]
    assert o.subtotal == D("160.00") and o.total == D("190.40")


def test_cli_reprice(tmp_path):
    data = tmp_path / "shop.json"
    storage.save(make_shop(), data)
    run_cli(data, "order", "CAP-RED:3", "CAP-BLUE:7", "--customer", "Kim")
    assert run_cli(data, "price-set", "CAP-BLUE", "20.00").returncode == 0
    r = run_cli(data, "reprice", "1001")
    assert r.returncode == 0, r.stderr
    # CAP-RED 3 x 12.00 + CAP-BLUE 7 x 16.00 = 148.00, 세금 28.12, 무료 배송
    assert r.stdout.strip() == "주문 1001 다시 계산 (합계 176.12)"


def test_cli_order(tmp_path):
    data = tmp_path / "shop.json"
    storage.save(make_shop(), data)
    r = run_cli(data, "order", "TSHIRT-S:5", "TSHIRT-L:5", "--customer", "Kim")
    assert r.stdout.strip() == "주문 1001 생성 (합계 240.86)"
    assert run_cli(data, "show", "1001").stdout.splitlines()[4:6] == [
        "  TSHIRT-S  T-Shirt (S)  5 x 17.99 = 89.95", "  TSHIRT-L  T-Shirt (L)  5 x 22.49 = 112.45"]
