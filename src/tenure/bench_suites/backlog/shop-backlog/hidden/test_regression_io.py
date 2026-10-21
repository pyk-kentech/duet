"""기존 동작 (데이터 파일 읽기, CSV, CLI 출력). 시작 코드와 바뀐 코드 모두에서 같아야 한다."""

import csv
import json
import os
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal as D

import pytest

from shop import Shop, StorageError, ValidationError
from shop import csvio, storage

T0 = datetime(2026, 3, 1, 12, 0)

V1 = {
    "version": 1,
    "locale": "default",
    "products": [{"sku": "BOOK", "name": "Python Book", "category": "books", "price_cents": 3000, "weight_g": 800,
                  "active": True},
                 {"sku": "MUG", "name": "Mug", "category": "home", "price_cents": 850, "weight_g": 350, "active": False}],
    "stock": {"BOOK": {"on_hand": 9, "reserved": 1}, "MUG": {"on_hand": 5, "reserved": 0}},
    "coupons": [{"code": "WELCOME", "kind": "fixed", "value": 500, "category": None, "min_cents": 2000,
                 "expires": None, "uses": 3},
                {"code": "TENOFF", "kind": "percent", "value": 10, "category": None, "min_cents": 0,
                 "expires": "2026-06-30", "uses": 0}],
    "orders": [
        {"id": 1001, "created": "2025-11-02T10:00:00", "customer": "Lee", "status": "refunded", "coupons": [],
         "shipping_cents": 490, "shipping_tax_cents": 93,
         "lines": [{"sku": "BOOK", "name": "Python Book", "category": "books", "qty": 1, "price_cents": 3000,
                    "discount_cents": 0, "tax_rate": 7, "tax_cents": 210}]},
        {"id": 1002, "created": "2025-11-03T11:00:00", "customer": "Park", "status": "pending",
         "coupons": ["WELCOME"], "shipping_cents": 490, "shipping_tax_cents": 93,
         "lines": [{"sku": "BOOK", "name": "Python Book", "category": "books", "qty": 1, "price_cents": 3000,
                    "discount_cents": 500, "tax_rate": 7, "tax_cents": 175}]},
    ],
    "refunds": [{"id": 1, "order_id": 1001, "created": "2025-11-05T10:00:00", "items": {"BOOK": 1},
                 "net_cents": 3000, "shipping_cents": 0, "tax_cents": 210}],
}

V2 = {
    "version": 2,
    "settings": {"locale": "eu", "tax_display": "inclusive"},
    "tax": {"default": 19.0, "rates": {"books": 7.0, "food": 7.0}},
    "products": [
        {"sku": "BOOK", "name": "Python Book", "category": "books", "price": 30.0, "weight_g": 800, "tiers": [],
         "active": True},
        {"sku": "TSHIRT", "name": "T-Shirt", "category": "apparel", "price": 19.99, "weight_g": 200,
         "tiers": [[10, 10.0]], "active": True},
    ],
    "variants": [{"sku": "TSHIRT-M", "product_sku": "TSHIRT", "attrs": {"size": "M"}, "price": None, "weight_g": None},
                 {"sku": "TSHIRT-XL", "product_sku": "TSHIRT", "attrs": {"size": "XL"}, "price": 21.5, "weight_g": 250}],
    "stock": {"on_hand": {"BOOK": 9, "TSHIRT-M": 48}, "reserved": {"TSHIRT-M": 2}},
    "coupons": [{"code": "SAVE10", "kind": "percent", "value": 10.0, "category": None, "min_subtotal": 0.0,
                 "stackable": False, "expires": "2026-12-31", "max_uses": None, "uses": 2}],
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


def write(tmp_path, data, name="shop.json"):
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def run_cli(data, *args, now="2026-03-01T12:00:00"):
    env = dict(os.environ, SHOP_NOW=now, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "shop", "--data", str(data), *args], capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=60)


def make_shop():
    s = Shop(clock=lambda: T0)
    s.add_product("BOOK", "Python Book", "books", "30.00", weight_g=800)
    s.add_product("MUG", "Mug", "home", "8.50", weight_g=350)
    for sku in ("BOOK", "MUG"):
        s.receive(sku, 100)
    return s


def test_load_version_1(tmp_path):
    s = storage.load(write(tmp_path, V1))
    assert s.catalog.product("BOOK").price == D("30.00") and s.catalog.product("MUG").active is False
    assert (s.inventory.on_hand, s.inventory.reserved) == ({"BOOK": 9, "MUG": 5}, {"BOOK": 1})
    w = s.coupon("WELCOME")
    assert (w.kind, w.value, w.min_subtotal, w.uses, w.stackable, w.max_uses) == ("fixed", D("5.00"), D("20.00"), 3,
                                                                                   False, None)
    assert s.coupon("TENOFF").value == 10 and s.coupon("TENOFF").expires == date(2026, 6, 30)
    a, b = s.get_order(1001), s.get_order(1002)
    assert (a.total, a.region, a.status, a.lines[0].list_price) == (D("37.93"), "domestic", "refunded", D("30.00"))
    assert (b.total, b.discount, b.coupons) == (D("32.58"), D("5.00"), ["WELCOME"])
    assert s.refunds[0].amount == D("32.10")
    assert (s.next_order_id, s.next_refund_id) == (1003, 2)
    assert (s.settings.locale, s.settings.tax_display) == ("default", "exclusive")


def test_load_version_2(tmp_path):
    s = storage.load(write(tmp_path, V2))
    assert s.get_order(1001).total == D("57.78") and s.get_order(1002).total == D("59.36")
    assert s.refunds[0].amount == D("28.89") and s.coupon("SAVE10").uses == 2
    xl = s.catalog.resolve("TSHIRT-XL")
    assert (xl.name, xl.price, xl.weight_g) == ("T-Shirt (XL)", D("21.50"), 250)
    assert s.catalog.resolve("TSHIRT-M").price == D("19.99")
    assert s.catalog.product("TSHIRT").tiers == [(10, D("10"))]
    assert (s.settings.locale, s.settings.tax_display) == ("eu", "inclusive")


def test_missing_products_is_storage_error(tmp_path):
    data = dict(V2)
    del data["products"]
    with pytest.raises(StorageError):
        storage.load(write(tmp_path, data))


def test_read_only_commands_do_not_rewrite(tmp_path):
    p = write(tmp_path, V2)
    before = p.read_bytes()
    for args in (["show", "1001"], ["orders"], ["report", "daily", "2026-02-10"], ["coupons"], ["products"],
                 ["report", "tax", "2026-02-01", "2026-02-28"], ["quote", "BOOK"]):
        r = run_cli(p, *args)
        assert r.returncode == 0, (args, r.stderr)
    assert p.read_bytes() == before


def _rows(path, delim):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f, delimiter=delim))


def test_csv_export_eu_locale(tmp_path):
    s = storage.load(write(tmp_path, V2))
    assert csvio.export_orders(s, tmp_path / "o.csv") == 2
    rows = _rows(tmp_path / "o.csv", ";")
    assert rows[0][:11] == ["order_id", "date", "customer", "status", "sku", "name", "qty", "unit_price", "discount",
                            "net", "tax"]
    assert rows[1][:11] == ["1001", "2026-02-10", "Kim", "shipped", "BOOK", "Python Book", "2", "30,00", "6,00",
                            "54,00", "3,78"]
    assert rows[2][:11] == ["1002", "2026-02-12", "Lee", "paid", "TSHIRT-M", "T-Shirt (M)", "2", "19,99", "0,00",
                            "39,98", "7,60"]


def test_csv_export_net_amounts_and_all_statuses(tmp_path):
    s = make_shop()
    s.settings.set("tax_display", "inclusive")
    a = s.checkout([("MUG", 2)], "Kim; Jr.")
    b = s.checkout([("BOOK", 1)], "Lee")
    s.cancel(b.id)
    csvio.export_orders(s, tmp_path / "o.csv")
    rows = _rows(tmp_path / "o.csv", ",")
    assert [r[:11] for r in rows[1:]] == [
        [str(a.id), "2026-03-01", "Kim; Jr.", "pending", "MUG", "Mug", "2", "8.50", "0.00", "17.00", "3.23"],
        [str(b.id), "2026-03-01", "Lee", "cancelled", "BOOK", "Python Book", "1", "30.00", "0.00", "30.00", "2.10"],
    ]


def test_csv_import_eu_locale(tmp_path):
    s = make_shop()
    s.settings.set("locale", "eu")
    p = tmp_path / "p.csv"
    p.write_text("sku;name;category;price;weight_g;tiers\nPEN;Pen;office;1,50;10;10:7,5|100:20\n", encoding="utf-8")
    assert csvio.import_products(s, p) == 1
    pen = s.catalog.product("PEN")
    assert pen.price == D("1.50") and pen.tiers == [(10, D("7.5")), (100, D("20"))]


def test_csv_import_existing_sku_reports_line(tmp_path):
    s = make_shop()
    p = tmp_path / "p.csv"
    p.write_text("sku,name,category,price,weight_g\nPEN,Pen,office,1.50,10\nMUG,Mug2,home,1,1\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="3행"):
        csvio.import_products(s, p)
    assert "PEN" not in s.catalog


def _show_shop():
    s = make_shop()
    s.add_coupon("BOOKS20", "category_percent", "20", category="books")
    o = s.checkout([("BOOK", 1), ("MUG", 2)], "Kim", coupons=["BOOKS20"])
    s.pay(o.id)
    s.ship(o.id)
    s.refund(o.id, {"MUG": 1})
    return s


def test_cli_show_full_format(tmp_path):
    p = tmp_path / "shop.json"
    storage.save(_show_shop(), p)
    assert run_cli(p, "show", "1001").stdout.splitlines() == [
        "주문 1001 (shipped)",
        "고객: Kim",
        "날짜: 2026-03-01 12:00",
        "지역: domestic",
        "쿠폰: BOOKS20",
        "  BOOK  Python Book  1 x 30.00 = 30.00",
        "  MUG  Mug  2 x 8.50 = 17.00",
        "소계: 47.00",
        "할인: -6.00",
        "배송: 4.90",
        "세금: 5.84",
        "합계: 51.74",
        "환불: -10.12",
    ]


def test_cli_inclusive_display_changes_lines_only(tmp_path):
    p = tmp_path / "shop.json"
    storage.save(_show_shop(), p)
    assert run_cli(p, "config", "tax_display", "inclusive").returncode == 0
    out = run_cli(p, "show", "1001").stdout.splitlines()
    assert out[5:12] == ["  BOOK  Python Book  1 x 32.10 = 32.10", "  MUG  Mug  2 x 10.12 = 20.23", "소계: 47.00",
                         "할인: -6.00", "배송: 4.90", "세금: 5.84", "합계: 51.74"]
    q = run_cli(p, "quote", "MUG:2").stdout.splitlines()
    assert q == ["  MUG  Mug  2 x 10.12 = 20.23", "소계: 17.00", "배송: 4.90", "세금: 4.16", "합계: 26.06"]


def test_cli_orders_listing_and_filter(tmp_path):
    s = make_shop()
    a = s.checkout([("MUG", 2)], "Kim")
    b = s.checkout([("BOOK", 1)], "Lee")
    s.pay(b.id)
    p = tmp_path / "shop.json"
    storage.save(s, p)
    assert run_cli(p, "orders").stdout.splitlines() == ["1001\t2026-03-01\tKim\tpending\t26.06",
                                                         "1002\t2026-03-01\tLee\tpaid\t37.93"]
    assert run_cli(p, "orders", "--status", "paid").stdout.splitlines() == ["1002\t2026-03-01\tLee\tpaid\t37.93"]
    assert run_cli(p, "orders", "--status", "lost").returncode == 1


def test_cli_coupons_listing_existing_kinds(tmp_path):
    p = tmp_path / "shop.json"
    storage.save(make_shop(), p)
    run_cli(p, "coupon-add", "BOOKS15", "category_percent", "15", "--category", "books", "--max-uses", "50")
    run_cli(p, "coupon-add", "HALF", "percent", "12.5")
    run_cli(p, "coupon-add", "TWO", "fixed", "2.5")
    run_cli(p, "coupon-add", "SHIP", "free_shipping", "--expires", "2026-12-31")
    assert run_cli(p, "coupon-add", "BAD", "percent", "150").returncode == 1
    assert run_cli(p, "coupons").stdout.splitlines() == [
        "BOOKS15\tcategory_percent\t15%\t0/50", "HALF\tpercent\t12.5%\t0/-", "SHIP\tfree_shipping\t-\t0/-",
        "TWO\tfixed\t2.50\t0/-"]


def test_cli_report_tax_rate_format(tmp_path):
    p = tmp_path / "shop.json"
    storage.save(make_shop(), p)
    run_cli(p, "tax-rate", "home", "7.5")
    run_cli(p, "order", "MUG:2", "--customer", "Kim")
    run_cli(p, "pay", "1001")
    assert run_cli(p, "report", "tax", "2026-03-01", "2026-03-01").stdout.splitlines() == \
        ["7.5%\t17.00\t1.28", "19%\t4.90\t0.93"]


def test_cli_errors(tmp_path):
    p = tmp_path / "shop.json"
    storage.save(make_shop(), p)
    before = p.read_bytes()
    for args in (["show", "9999"], ["pay", "9999"], ["order", "NOPE", "--customer", "Kim"],
                 ["refund", "1001", "MUG:1", "--all"]):
        r = run_cli(p, *args)
        assert r.returncode == 1 and r.stderr.startswith("오류:"), args
    assert p.read_bytes() == before


def test_cli_summary_counts_every_status(tmp_path):
    s = make_shop()
    s.checkout([("MUG", 2)], "Kim")
    b = s.checkout([("BOOK", 1)], "Lee")
    s.pay(b.id)
    c = s.checkout([("MUG", 1)], "Park")
    s.cancel(c.id)
    p = tmp_path / "shop.json"
    storage.save(s, p)
    assert run_cli(p, "summary").stdout.splitlines() == [
        "pending\t1\t26.06", "paid\t1\t37.93", "shipped\t0\t0.00", "cancelled\t1\t15.95", "refunded\t0\t0.00"]
