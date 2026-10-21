from decimal import Decimal as D

import pytest

from shop import Catalog, NotFound, ValidationError
from shop.money import allocate, fmt, parse_money, percent_of, round_money, to_decimal


def test_round_money_half_up():
    assert round_money(D("0.125")) == D("0.13")
    assert round_money(D("2.675")) == D("2.68")
    assert round_money(D("-1.005")) == D("-1.01")


def test_fmt_two_decimals():
    assert fmt(D("12.3")) == "12.30"
    assert fmt(D("0")) == "0.00"
    assert fmt(D("-5")) == "-5.00"


def test_parse_money_rules():
    assert parse_money("19.9") == D("19.9")
    with pytest.raises(ValidationError):
        parse_money("1.234")
    with pytest.raises(ValidationError):
        parse_money("-1")
    with pytest.raises(ValidationError):
        parse_money("abc")


def test_to_decimal_float_uses_repr():
    assert to_decimal(19.99) == D("19.99")


def test_percent_of():
    assert percent_of(D("33.33"), D("10")) == D("3.33")


def test_allocate_sums_and_remainder_to_largest():
    parts = allocate(D("10.00"), [D("1"), D("1"), D("1")])
    assert sum(parts) == D("10.00")
    assert parts == [D("3.34"), D("3.33"), D("3.33")]
    assert allocate(D("1.00"), [D("0"), D("0")]) == [D("0.00"), D("0.00")]


def test_add_product_and_duplicate():
    c = Catalog()
    p = c.add_product("BOOK", " Python Book ", "books", "30.00", weight_g=800)
    assert p.name == "Python Book" and p.price == D("30.00")
    with pytest.raises(ValidationError):
        c.add_product("BOOK", "Again", "books", "1.00")


@pytest.mark.parametrize("sku", ["book", "", "A B", "X" * 33])
def test_bad_sku(sku):
    with pytest.raises(ValidationError):
        Catalog().add_product(sku, "N", "misc", "1.00")


def test_variant_resolve_and_name(shop):
    s = shop.catalog.resolve("TSHIRT-L")
    assert s.name == "T-Shirt (red, L)" and s.price == D("21.99") and s.product_sku == "TSHIRT"
    assert shop.catalog.resolve("TSHIRT-M").price == D("19.99")


def test_product_with_variants_not_sellable(shop):
    with pytest.raises(ValidationError):
        shop.catalog.resolve("TSHIRT")
    with pytest.raises(NotFound):
        shop.catalog.resolve("NOPE")


def test_inactive_not_sellable(shop):
    shop.catalog.set_active("MUG", False)
    with pytest.raises(ValidationError):
        shop.catalog.resolve("MUG")
    assert "MUG" not in [s.sku for s in shop.catalog.sellables()]


def test_tiers_parse_and_percent(shop):
    assert shop.catalog.product("TEA").tiers == [(10, D("5")), (50, D("10"))]
    assert shop.catalog.tier_percent("TEA", 9) == 0
    assert shop.catalog.tier_percent("TEA", 10) == D("5")
    assert shop.catalog.tier_percent("TEA", 70) == D("10")
    with pytest.raises(ValidationError):
        Catalog().add_product("X1", "X", "misc", "1.00", tiers="1:5")


def test_sellables_sorted(shop):
    assert [s.sku for s in shop.catalog.sellables()] == ["BOOK", "MUG", "TEA", "TSHIRT-L", "TSHIRT-M"]
