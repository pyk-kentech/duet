import csv
import json
from decimal import Decimal as D

import pytest

from shop import StorageError, ValidationError, csvio, storage


def _full(shop):
    shop.add_coupon("SAVE10", "percent", "10", max_uses=5)
    o = shop.checkout([("BOOK", 1), ("TSHIRT-L", 2)], "Kim", coupons=["SAVE10"])
    shop.pay(o.id)
    shop.ship(o.id)
    shop.refund(o.id, {"TSHIRT-L": 1})
    shop.checkout([("TEA", 3)], "Lee")
    return o


def test_round_trip(shop, tmp_path):
    o = _full(shop)
    path = tmp_path / "s.json"
    storage.save(shop, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == storage.FORMAT_VERSION
    s2 = storage.load(path)
    o2 = s2.get_order(o.id)
    assert (o2.total, o2.status, o2.coupons, o2.paid_at) == (o.total, o.status, o.coupons, o.paid_at)
    assert [ln.sku for ln in o2.lines] == ["BOOK", "TSHIRT-L"]
    assert s2.refunds[0].amount == shop.refunds[0].amount
    assert s2.coupon("SAVE10").uses == 1 and s2.coupon("SAVE10").max_uses == 5
    assert s2.inventory.reserved == shop.inventory.reserved
    assert s2.catalog.resolve("TSHIRT-L").name == "T-Shirt (red, L)"
    assert s2.next_order_id == shop.next_order_id


def test_missing_file_is_empty_shop(tmp_path):
    s = storage.load(tmp_path / "none.json")
    assert s.orders == [] and s.catalog.products() == []


def test_unknown_version(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"version": 99, "products": []}), encoding="utf-8")
    with pytest.raises(StorageError):
        storage.load(p)


def test_broken_json(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{nope", encoding="utf-8")
    with pytest.raises(StorageError):
        storage.load(p)


def test_export_orders_default_locale(shop, tmp_path):
    o = _full(shop)
    path = tmp_path / "o.csv"
    assert csvio.export_orders(shop, path) == 3
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0][:4] == ["order_id", "date", "customer", "status"]
    assert rows[1][:9] == [str(o.id), "2026-03-01", "Kim", "shipped", "BOOK", "Python Book", "1", "30.00", "3.00"]


def test_import_products(shop, tmp_path):
    p = tmp_path / "p.csv"
    p.write_text("sku,name,category,price,weight_g,tiers\nPEN,Pen,office,1.50,10,10:5|100:20\nINK,Ink,office,3,20,\n",
                 encoding="utf-8")
    assert csvio.import_products(shop, p) == 2
    assert shop.catalog.product("PEN").tiers == [(10, D("5")), (100, D("20"))]
    assert shop.catalog.product("INK").price == D("3")


def test_import_products_all_or_nothing(shop, tmp_path):
    p = tmp_path / "p.csv"
    p.write_text("sku,name,category,price,weight_g\nPEN,Pen,office,1.50,10\nbad sku,X,office,1,1\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="3행"):
        csvio.import_products(shop, p)
    assert "PEN" not in shop.catalog
