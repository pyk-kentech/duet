"""티켓 6: 데이터 파일 형식 버전 3 (Decimal 값은 문자열)."""

import json
import os
import re
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal as D

import pytest

from shop import Shop, StorageError
from shop import reports, storage

T0 = datetime(2026, 3, 1, 12, 0)
MONEY = re.compile(r"^-?\d+\.\d\d$")

V2 = {
    "version": 2,
    "settings": {"locale": "eu", "tax_display": "inclusive"},
    "tax": {"default": 19.0, "rates": {"books": 7.0, "food": 7.0, "kids": 7.5}},
    "products": [
        {"sku": "BOOK", "name": "Python Book", "category": "books", "price": 30.0, "weight_g": 800, "tiers": [],
         "active": True},
        {"sku": "TSHIRT", "name": "T-Shirt", "category": "apparel", "price": 19.99, "weight_g": 200,
         "tiers": [[10, 10.0], [50, 12.5]], "active": True},
    ],
    "variants": [{"sku": "TSHIRT-M", "product_sku": "TSHIRT", "attrs": {"size": "M"}, "price": None, "weight_g": None},
                 {"sku": "TSHIRT-XL", "product_sku": "TSHIRT", "attrs": {"size": "XL"}, "price": 21.5, "weight_g": 250}],
    "stock": {"on_hand": {"BOOK": 9, "TSHIRT-M": 48, "TSHIRT-XL": 3}, "reserved": {"TSHIRT-M": 2}},
    "coupons": [{"code": "SAVE10", "kind": "percent", "value": 10.0, "category": None, "min_subtotal": 0.0,
                 "stackable": False, "expires": "2026-12-31", "max_uses": None, "uses": 2},
                {"code": "FIVE", "kind": "fixed", "value": 5.0, "category": None, "min_subtotal": 20.0,
                 "stackable": True, "expires": None, "max_uses": 100, "uses": 7}],
    "orders": [
        {"id": 1001, "created": "2026-02-10T09:30:00", "customer": "Kim", "region": "domestic", "status": "shipped",
         "coupons": ["SAVE10"], "shipping": 0.0, "shipping_tax": 0.0, "paid_at": "2026-02-10T09:35:00",
         "shipped_at": "2026-02-11T08:00:00",
         "lines": [{"sku": "BOOK", "name": "Python Book", "category": "books", "qty": 2, "list_price": 30.0,
                    "unit_price": 30.0, "discount": 6.0, "tax_rate": 7.0, "tax": 3.78}]},
        {"id": 1002, "created": "2026-02-12T14:00:00", "customer": "Lee", "region": "eu", "status": "paid",
         "coupons": [], "shipping": 9.9, "shipping_tax": 1.88, "paid_at": "2026-02-12T14:01:00", "shipped_at": None,
         "lines": [{"sku": "TSHIRT-M", "name": "T-Shirt (M)", "category": "apparel", "qty": 2, "list_price": 19.99,
                    "unit_price": 19.99, "discount": 0.0, "tax_rate": 19.0, "tax": 7.6}]},
    ],
    "refunds": [{"id": 1, "order_id": 1001, "created": "2026-02-15T10:00:00", "items": {"BOOK": 1}, "net": 27.0,
                 "shipping": 0.0, "tax": 1.89, "reason": ""}],
    "next_order_id": 1003,
    "next_refund_id": 2,
}


def walk(x):
    yield x
    if isinstance(x, dict):
        for v in x.values():
            yield from walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk(v)


def make_shop():
    s = Shop(clock=lambda: T0)
    s.add_product("BOOK", "Python Book", "books", "30", weight_g=800)
    s.add_product("MUG", "Mug", "home", "8.5", weight_g=350, tiers="10:7.5")
    s.add_product("TSHIRT", "T-Shirt", "apparel", "19.9", weight_g=200)
    s.add_variant("TSHIRT", "TSHIRT-M", attrs={"size": "M"}, price="21")
    s.tax_table.set_rate("kids", "7.5")
    for sku in ("BOOK", "MUG", "TSHIRT-M"):
        s.receive(sku, 50)
    s.add_coupon("FIVE", "fixed", "5", min_subtotal="20", stackable=True)
    s.add_coupon("SAVE10", "percent", "10", stackable=True, max_uses=9, expires=date(2026, 12, 31))
    o = s.checkout([("BOOK", 1), ("MUG", 3), ("TSHIRT-M", 1)], "Kim", coupons=["SAVE10", "FIVE"])
    s.pay(o.id)
    s.ship(o.id)
    s.refund(o.id, {"MUG": 1})
    s.checkout([("MUG", 1)], "Lee", region="eu")
    return s


def saved(tmp_path, shop):
    path = tmp_path / "s.json"
    storage.save(shop, path)
    return path, json.loads(path.read_text(encoding="utf-8"))


def test_save_writes_version_3(tmp_path):
    _, data = saved(tmp_path, make_shop())
    assert data["version"] == 3


def test_no_floats_left(tmp_path):
    _, data = saved(tmp_path, make_shop())
    floats = [x for x in walk(data) if isinstance(x, float)]
    assert floats == []


def test_money_fields_are_two_decimal_strings(tmp_path):
    _, data = saved(tmp_path, make_shop())
    prices = {p["sku"]: p["price"] for p in data["products"]}
    assert prices == {"BOOK": "30.00", "MUG": "8.50", "TSHIRT": "19.90"}
    assert [v["price"] for v in data["variants"]] == ["21.00"]
    money = []
    for o in data["orders"]:
        money += [o["shipping"], o["shipping_tax"]]
        for ln in o["lines"]:
            money += [ln["list_price"], ln["unit_price"], ln["discount"], ln["tax"]]
    for r in data["refunds"]:
        money += [r["net"], r["shipping"], r["tax"]]
    coupons = {c["code"]: c for c in data["coupons"]}
    money += [coupons["FIVE"]["value"], coupons["FIVE"]["min_subtotal"], coupons["SAVE10"]["min_subtotal"]]
    assert all(isinstance(m, str) and MONEY.match(m) for m in money), money
    assert data["orders"][1]["shipping"] == "9.90" and coupons["FIVE"]["value"] == "5.00"


def test_rates_are_strings_with_same_value(tmp_path):
    _, data = saved(tmp_path, make_shop())
    assert isinstance(data["tax"]["default"], str) and D(data["tax"]["default"]) == 19
    assert {k: D(v) for k, v in data["tax"]["rates"].items()} == {"books": 7, "food": 7, "kids": D("7.5")}
    mug = next(p for p in data["products"] if p["sku"] == "MUG")
    assert [(q, D(p)) for q, p in mug["tiers"]] == [(10, D("7.5"))] and isinstance(mug["tiers"][0][1], str)
    assert D(next(c for c in data["coupons"] if c["code"] == "SAVE10")["value"]) == 10
    assert all(isinstance(ln["tax_rate"], str) for o in data["orders"] for ln in o["lines"])


def test_v3_round_trip_preserves_everything(tmp_path):
    shop = make_shop()
    path, _ = saved(tmp_path, shop)
    s2 = storage.load(path)
    for o in shop.orders_list():
        o2 = s2.get_order(o.id)
        assert (o2.total, o2.tax, o2.shipping, o2.status, o2.coupons, o2.region, o2.paid_at) == \
               (o.total, o.tax, o.shipping, o.status, o.coupons, o.region, o.paid_at)
        assert [(a.sku, a.qty, a.unit_price, a.discount, a.tax_rate, a.tax) for a in o2.lines] == \
               [(a.sku, a.qty, a.unit_price, a.discount, a.tax_rate, a.tax) for a in o.lines]
    assert [(r.id, r.items, r.amount) for r in s2.refunds] == [(r.id, r.items, r.amount) for r in shop.refunds]
    c = s2.coupon("SAVE10")
    assert (c.value, c.stackable, c.max_uses, c.uses, c.expires) == (10, True, 9, 1, date(2026, 12, 31))
    assert s2.coupon("FIVE").min_subtotal == 20
    assert s2.catalog.product("MUG").tiers == [(10, D("7.5"))]
    assert s2.tax_table.rate_for("kids") == D("7.5")
    assert (s2.inventory.on_hand, s2.inventory.reserved) == (shop.inventory.on_hand, shop.inventory.reserved)
    assert (s2.next_order_id, s2.next_refund_id) == (shop.next_order_id, shop.next_refund_id)
    path2, _ = saved(tmp_path / "again", s2)
    assert json.loads(path2.read_text(encoding="utf-8")) == json.loads(path.read_text(encoding="utf-8"))


def test_v2_file_upgrades_with_same_values(tmp_path):
    old = tmp_path / "old.json"
    old.write_text(json.dumps(V2), encoding="utf-8")
    s = storage.load(old)
    path, data = saved(tmp_path, s)
    assert data["version"] == 3
    assert data["orders"][0]["lines"][0]["discount"] == "6.00" and data["orders"][1]["shipping"] == "9.90"
    s3 = storage.load(path)
    assert s3.get_order(1001).total == D("57.78") and s3.get_order(1002).total == D("59.36")
    assert s3.refunds[0].amount == D("28.89")
    assert s3.catalog.resolve("TSHIRT-XL").price == D("21.5")
    assert s3.catalog.product("TSHIRT").tiers == [(10, D("10")), (50, D("12.5"))]
    assert (s3.settings.locale, s3.settings.tax_display) == ("eu", "inclusive")
    assert s3.coupon("FIVE").uses == 7 and s3.next_order_id == 1003


def v3_from_v2():
    """V2 를 손으로 버전 3 형식으로 바꾼 것 (티켓 6 의 규칙대로)."""
    d = json.loads(json.dumps(V2))
    d["version"] = 3

    def m(x):
        return None if x is None else f"{x:.2f}"

    def r(x):
        return format(D(repr(x)).normalize(), "f")

    d["tax"] = {"default": r(d["tax"]["default"]), "rates": {k: r(v) for k, v in d["tax"]["rates"].items()}}
    for p in d["products"]:
        p["price"] = m(p["price"])
        p["tiers"] = [[q, r(x)] for q, x in p["tiers"]]
    for v in d["variants"]:
        v["price"] = m(v["price"])
    for c in d["coupons"]:
        c["value"] = m(c["value"]) if c["kind"] == "fixed" else r(c["value"])
        c["min_subtotal"] = m(c["min_subtotal"])
    for o in d["orders"]:
        o["shipping"], o["shipping_tax"], o["channel"] = m(o["shipping"]), m(o["shipping_tax"]), "web"
        for ln in o["lines"]:
            for k in ("list_price", "unit_price", "discount", "tax"):
                ln[k] = m(ln[k])
            ln["tax_rate"] = r(ln["tax_rate"])
    for x in d["refunds"]:
        for k in ("net", "shipping", "tax"):
            x[k] = m(x[k])
    return d


def test_reads_hand_written_v3(tmp_path):
    p = tmp_path / "v3.json"
    p.write_text(json.dumps(v3_from_v2()), encoding="utf-8")
    s = storage.load(p)
    assert s.get_order(1001).total == D("57.78") and s.get_order(1002).total == D("59.36")
    assert s.get_order(1001).lines[0].discount == D("6.00") and s.refunds[0].tax == D("1.89")
    assert s.coupon("FIVE").value == D("5.00") and s.coupon("SAVE10").value == 10
    assert s.catalog.product("TSHIRT").tiers == [(10, D("10")), (50, D("12.5"))]
    assert s.tax_table.rate_for("kids") == D("7.5")
    assert reports.daily_sales(s, date(2026, 2, 12)).gross == D("59.36")


@pytest.mark.parametrize("version", [4, 0, None])
def test_unknown_versions_rejected(tmp_path, version):
    data = dict(V2)
    if version is None:
        del data["version"]
    else:
        data["version"] = version
    p = tmp_path / "s.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(StorageError) as e:
        storage.load(p)
    if version == 4:
        assert "4" in str(e.value)


def test_cli_write_upgrades_v2_file(tmp_path):
    p = tmp_path / "shop.json"
    p.write_text(json.dumps(V2), encoding="utf-8")
    env = dict(os.environ, SHOP_NOW="2026-03-01T12:00:00", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-m", "shop", "--data", str(p), "receive", "BOOK", "1"], capture_output=True,
                       text=True, encoding="utf-8", env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["version"] == 3 and data["stock"]["on_hand"]["BOOK"] == 10
    assert data["refunds"][0]["tax"] == "1.89"
