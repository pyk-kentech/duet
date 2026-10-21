"""기존 동작 (가격·쿠폰·배송·견적). 시작 코드와 바뀐 코드 모두에서 같아야 한다."""

from datetime import date, datetime
from decimal import Decimal as D

import pytest

from shop import CouponError, Shop, ValidationError

T0 = datetime(2026, 3, 1, 12, 0)


def make_shop():
    s = Shop(clock=lambda: T0)
    s.add_product("BOOK", "Python Book", "books", "30.00", weight_g=800)
    s.add_product("NOVEL", "Novel", "books", "12.00", weight_g=300)
    s.add_product("MUG", "Mug", "home", "8.50", weight_g=350)
    s.add_product("PEN", "Pen", "office", "0.99", weight_g=10, tiers="10:5")
    s.add_product("TEA", "Green Tea", "food", "4.20", weight_g=100, tiers="10:5,50:10")
    s.add_product("BAG", "Bag", "apparel", "12.00", weight_g=400)
    s.add_product("HAT", "Hat", "apparel", "12.00", weight_g=150)
    s.add_product("ANVIL", "Anvil", "home", "20.00", weight_g=1000)
    for sku in ("BOOK", "NOVEL", "MUG", "PEN", "TEA", "BAG", "HAT", "ANVIL"):
        s.receive(sku, 500)
    return s


def disc(order):
    return [ln.discount for ln in order.lines]


def test_tier_discount_rounded_per_unit():
    o = make_shop().checkout([("PEN", 10)], "Kim")
    assert o.lines[0].unit_price == D("0.94") and o.subtotal == D("9.40")


def test_tiers_of_different_products_not_combined():
    o = make_shop().checkout([("TEA", 6), ("PEN", 6)], "Kim")
    assert [ln.unit_price for ln in o.lines] == [D("4.20"), D("0.99")]


def test_highest_reached_tier_applies():
    s = make_shop()
    assert s.checkout([("TEA", 50)], "Kim").lines[0].unit_price == D("3.78")
    assert s.checkout([("TEA", 49)], "Kim").lines[0].unit_price == D("3.99")


def test_coupon_application_order():
    s = make_shop()
    s.add_coupon("FIVE", "fixed", "5", stackable=True)
    s.add_coupon("SAVE10", "percent", "10", stackable=True)
    s.add_coupon("BOOKS20", "category_percent", "20", category="books", stackable=True)
    o = s.checkout([("BOOK", 1), ("MUG", 2)], "Kim", coupons=["FIVE", "SAVE10", "BOOKS20"])
    assert disc(o) == [D("11.33"), D("3.77")] and o.discount == D("15.10")
    assert [ln.tax for ln in o.lines] == [D("1.31"), D("2.51")]


def test_allocation_remainder_goes_to_largest_line():
    s = make_shop()
    s.add_coupon("TEN", "fixed", "10")
    assert disc(s.checkout([("NOVEL", 1), ("BAG", 1), ("HAT", 1)], "Kim", coupons=["TEN"])) == \
        [D("3.34"), D("3.33"), D("3.33")]
    s.add_coupon("ONE", "fixed", "1")
    assert disc(s.checkout([("BAG", 1), ("MUG", 1), ("PEN", 1)], "Kim", coupons=["ONE"])) == \
        [D("0.55"), D("0.40"), D("0.05")]


def test_fixed_after_percent_capped_at_remaining():
    s = make_shop()
    s.add_coupon("HALF", "percent", "50", stackable=True)
    s.add_coupon("BIG", "fixed", "100", stackable=True)
    o = s.checkout([("MUG", 1)], "Kim", coupons=["BIG", "HALF"])
    assert disc(o) == [D("8.50")] and o.lines[0].tax == 0 and o.total == D("5.83")


def test_free_shipping_coupon_combines_with_non_stackable():
    s = make_shop()
    s.add_coupon("SAVE10", "percent", "10")
    s.add_coupon("SHIP", "free_shipping")
    o = s.checkout([("BOOK", 1)], "Kim", region="eu", coupons=["SHIP", "SAVE10"])
    assert disc(o) == [D("3.00")] and o.shipping == 0 and o.shipping_tax == 0


def test_non_stackable_among_stackables_rejected():
    s = make_shop()
    s.add_coupon("AAA", "percent", "5", stackable=True)
    s.add_coupon("BBB", "fixed", "1", stackable=True)
    s.add_coupon("CCC", "fixed", "2")
    with pytest.raises(CouponError):
        s.checkout([("BOOK", 1)], "Kim", coupons=["AAA", "BBB", "CCC"])
    assert s.checkout([("BOOK", 1)], "Kim", coupons=["AAA", "BBB"]).discount == D("2.50")


def test_min_subtotal_after_tier_boundary():
    s = make_shop()
    s.add_coupon("M940", "fixed", "1", min_subtotal="9.40")
    s.add_coupon("M941", "fixed", "1", min_subtotal="9.41")
    assert s.checkout([("PEN", 10)], "Kim", coupons=["M940"]).discount == D("1.00")
    with pytest.raises(CouponError):
        s.checkout([("PEN", 10)], "Kim", coupons=["M941"])


def test_coupon_valid_through_expiry_day():
    s = make_shop()
    s.add_coupon("TODAY", "percent", "10", expires=date(2026, 3, 1))
    s.add_coupon("YDAY", "percent", "10", expires="2026-02-28")
    assert s.checkout([("BOOK", 1)], "Kim", coupons=["TODAY"]).discount == D("3.00")
    with pytest.raises(CouponError):
        s.checkout([("BOOK", 1)], "Kim", coupons=["YDAY"])


def test_coupon_codes_case_insensitive():
    s = make_shop()
    c = s.add_coupon("Save10", "percent", "10")
    assert c.code == "SAVE10" and s.coupon("sAvE10") is c
    assert s.checkout([("BOOK", 1)], "Kim", coupons=["save10"]).coupons == ["SAVE10"]
    with pytest.raises(CouponError):
        s.checkout([("BOOK", 1)], "Kim", coupons=["SAVE10", "save10"])


def test_free_shipping_threshold_before_coupons():
    s = make_shop()
    s.add_coupon("SAVE20", "percent", "20")
    o = s.checkout([("BOOK", 2)], "Kim", coupons=["SAVE20"])
    assert o.net == D("48.00") and o.shipping == 0
    assert s.checkout([("BOOK", 2)], "Kim", region="eu").shipping == D("9.90")


def test_weight_surcharge_per_started_kg():
    s = make_shop()
    assert s.checkout([("ANVIL", 2)], "Kim").shipping == D("4.90")
    assert s.checkout([("ANVIL", 2), ("PEN", 1)], "Kim").shipping == D("5.90")
    assert s.checkout([("ANVIL", 3)], "Kim", region="eu").shipping == D("12.40")
    assert s.checkout([("ANVIL", 3), ("PEN", 1)], "Kim", region="eu").shipping == D("14.90")
    assert s.checkout([("ANVIL", 3), ("PEN", 1)], "Kim", region="world").shipping == D("29.90")


def test_quote_leaves_stock_and_coupon_uses():
    s = make_shop()
    s.add_coupon("ONCE", "fixed", "5", max_uses=1)
    q1 = s.quote([("BOOK", 1)], coupons=["ONCE"])
    q2 = s.quote([("BOOK", 1)], coupons=["once"])
    assert q1.total == q2.total == D("32.58")
    assert s.coupon("ONCE").uses == 0 and s.inventory.reserved == {}
    assert s.quote([("BOOK", 600)]).subtotal == D("18000.00")


def test_quote_checks_coupons_like_checkout():
    s = make_shop()
    s.add_coupon("OLD", "percent", "10", expires="2026-02-01")
    with pytest.raises(CouponError):
        s.quote([("BOOK", 1)], coupons=["OLD"])
    with pytest.raises(CouponError):
        s.quote([("BOOK", 1)], coupons=["NOPE"])


def test_variant_without_attrs_falls_back():
    s = make_shop()
    s.add_variant("BAG", "BAG-X")
    item = s.catalog.resolve("BAG-X")
    assert (item.name, item.price, item.weight_g, item.category) == ("Bag (BAG-X)", D("12.00"), 400, "apparel")
    with pytest.raises(ValidationError):
        s.checkout([("BAG", 1)], "Kim")
