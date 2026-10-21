from datetime import date
from decimal import Decimal as D

import pytest

from shop import CouponError, ValidationError


def test_single_sku_quantity_tier(shop):
    o = shop.checkout([("TEA", 10)], "Kim")
    assert o.lines[0].unit_price == D("3.99") and o.lines[0].list_price == D("4.20")
    o = shop.checkout([("TEA", 50)], "Kim")
    assert o.lines[0].unit_price == D("3.78")


def test_same_sku_merged(shop):
    o = shop.checkout([("TEA", 6), ("BOOK", 1), ("TEA", 4)], "Kim")
    assert [(ln.sku, ln.qty) for ln in o.lines] == [("TEA", 10), ("BOOK", 1)]
    assert o.lines[0].unit_price == D("3.99")


def test_basic_totals(shop):
    o = shop.checkout([("BOOK", 1), ("MUG", 2)], "Kim")
    assert o.subtotal == D("47.00")
    assert o.shipping == D("4.90") and o.shipping_tax == D("0.93")
    assert [ln.tax for ln in o.lines] == [D("2.10"), D("3.23")]
    assert o.tax == D("6.26") and o.total == D("58.16")


def test_percent_coupon_allocated(shop):
    shop.add_coupon("SAVE10", "percent", "10")
    o = shop.checkout([("BOOK", 1), ("MUG", 2)], "Kim", coupons=["save10"])
    assert [ln.discount for ln in o.lines] == [D("3.00"), D("1.70")]
    assert [ln.tax for ln in o.lines] == [D("1.89"), D("2.91")]
    assert o.coupons == ["SAVE10"] and o.total == D("52.93")
    assert shop.coupon("SAVE10").uses == 1


def test_fixed_coupon_capped(shop):
    shop.add_coupon("BIG", "fixed", "100")
    o = shop.checkout([("MUG", 1)], "Kim", coupons=["BIG"])
    assert o.discount == D("8.50") and o.net == 0 and o.lines[0].tax == 0
    assert o.total == D("5.83")


def test_category_percent_only_matching_lines(shop):
    shop.add_coupon("BOOKS20", "category_percent", "20", category="books")
    o = shop.checkout([("BOOK", 1), ("MUG", 1)], "Kim", coupons=["BOOKS20"])
    assert [ln.discount for ln in o.lines] == [D("6.00"), D("0.00")]


def test_category_required_for_category_percent(shop):
    with pytest.raises(ValidationError):
        shop.add_coupon("NOCAT", "category_percent", "20")
    with pytest.raises(ValidationError):
        shop.add_coupon("BADKIND", "half", "20")


def test_non_stackable_coupons_rejected(shop):
    shop.add_coupon("AAA", "percent", "5")
    shop.add_coupon("BBB", "fixed", "2", stackable=True)
    with pytest.raises(CouponError):
        shop.checkout([("BOOK", 1)], "Kim", coupons=["AAA", "BBB"])
    assert shop.coupon("AAA").uses == 0 and shop.inventory.reserved == {}


def test_stackable_coupons_combine(shop):
    shop.add_coupon("AAA", "percent", "10", stackable=True)
    shop.add_coupon("BBB", "fixed", "2", stackable=True)
    o = shop.checkout([("BOOK", 1)], "Kim", coupons=["BBB", "AAA"])
    assert o.discount == D("5.00")          # 10% 먼저(3.00), 그다음 fixed 2.00


def test_expired_coupon(shop):
    shop.add_coupon("OLD", "percent", "10", expires=date(2026, 2, 28))
    with pytest.raises(CouponError):
        shop.checkout([("BOOK", 1)], "Kim", coupons=["OLD"])


def test_min_subtotal(shop):
    shop.add_coupon("MIN50", "fixed", "5", min_subtotal="50")
    with pytest.raises(CouponError):
        shop.checkout([("BOOK", 1), ("MUG", 2)], "Kim", coupons=["MIN50"])


def test_max_uses(shop):
    shop.add_coupon("ONCE", "fixed", "5", max_uses=1)
    shop.checkout([("BOOK", 1)], "Kim", coupons=["ONCE"])
    with pytest.raises(CouponError):
        shop.checkout([("BOOK", 1)], "Lee", coupons=["ONCE"])


def test_unknown_coupon(shop):
    with pytest.raises(CouponError):
        shop.checkout([("BOOK", 1)], "Kim", coupons=["NOPE1"])


def test_free_shipping_coupon_any_region(shop):
    shop.add_coupon("SHIPFREE", "free_shipping")
    o = shop.checkout([("BOOK", 1)], "Kim", region="eu", coupons=["SHIPFREE"])
    assert o.shipping == 0 and o.shipping_tax == 0


def test_shipping_rules(shop):
    assert shop.checkout([("MUG", 1)], "Kim", region="eu").shipping == D("9.90")
    assert shop.checkout([("BOOK", 2)], "Kim").shipping == D("0.00")          # 60.00 >= 50
    assert shop.checkout([("BOOK", 3)], "Kim", region="world").shipping == D("24.90")  # 2400g -> +1kg
    with pytest.raises(ValidationError):
        shop.checkout([("BOOK", 1)], "Kim", region="mars")
