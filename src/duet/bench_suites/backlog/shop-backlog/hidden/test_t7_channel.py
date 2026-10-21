"""티켓 7: 판매 채널 (web, store, phone)."""

import csv
import json
import os
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal as D

import pytest

from shop import Shop, ValidationError
from shop import csvio, reports, storage

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
    """web: BOOK 1 (37.93) / phone: MUG 2 (26.06) / store: NOVEL 2 (31.51) — 모두 결제."""
    s = make_shop()
    a = s.checkout([("BOOK", 1)], "Kim")
    b = s.checkout([("MUG", 2)], "Lee", channel="phone")
    c = s.checkout([("NOVEL", 2)], "Park", channel="store")
    for o in (a, b, c):
        s.pay(o.id)
    return s, a, b, c


def run_cli(data, *args):
    env = dict(os.environ, SHOP_NOW="2026-03-01T12:00:00", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "shop", "--data", str(data), *args], capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=60)


def test_default_and_given_channel():
    s, a, b, c = scenario()
    assert (a.channel, b.channel, c.channel) == ("web", "phone", "store")


def test_unknown_channel_rejected_without_side_effects():
    s = make_shop()
    with pytest.raises(ValidationError):
        s.checkout([("BOOK", 1)], "Kim", channel="fax")
    assert s.orders_list() == [] and s.inventory.reserved == {} and s.next_order_id == 1001


def test_orders_list_by_channel():
    s, a, b, c = scenario()
    assert [o.id for o in s.orders_list(channel="phone")] == [b.id]
    assert [o.id for o in s.orders_list(status="paid", channel="web")] == [a.id]
    assert len(s.orders_list()) == 3


def test_daily_sales_by_channel():
    s, a, b, c = scenario()
    r = reports.daily_sales(s, DAY, channel="phone")
    assert (r.orders, r.gross, r.tax) == (1, D("26.06"), D("4.16"))
    assert reports.daily_sales(s, DAY).orders == 3


def test_category_by_channel():
    s, a, b, c = scenario()
    assert reports.sales_by_category(s, DAY, DAY, channel="store") == {"books": D("24.00")}
    assert reports.sales_by_category(s, DAY, DAY, channel=None) == {"books": D("54.00"), "home": D("17.00")}


def test_top_products_by_channel():
    s, a, b, c = scenario()
    assert reports.top_products(s, channel="web") == [("BOOK", "Python Book", 1)]
    assert reports.top_products(s, n=1, channel="store") == [("NOVEL", "Novel", 2)]


def test_tax_report_by_channel():
    s, a, b, c = scenario()
    assert reports.tax_report(s, DAY, DAY, channel="phone") == [(D("19"), D("21.90"), D("4.16"))]


def test_storage_keeps_channel(tmp_path):
    s, a, b, c = scenario()
    storage.save(s, tmp_path / "s.json")
    data = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert [o["channel"] for o in data["orders"]] == ["web", "phone", "store"]
    s2 = storage.load(tmp_path / "s.json")
    assert [o.channel for o in s2.orders_list()] == ["web", "phone", "store"]


def test_old_files_are_web(tmp_path):
    p = tmp_path / "v2.json"
    p.write_text(json.dumps({
        "version": 2,
        "products": [{"sku": "BOOK", "name": "Python Book", "category": "books", "price": 30.0, "weight_g": 800}],
        "orders": [{"id": 1001, "created": "2026-02-10T09:30:00", "customer": "Kim", "region": "domestic",
                    "status": "paid", "coupons": [], "shipping": 4.9, "shipping_tax": 0.93,
                    "lines": [{"sku": "BOOK", "name": "Python Book", "category": "books", "qty": 1, "list_price": 30.0,
                               "unit_price": 30.0, "discount": 0.0, "tax_rate": 7.0, "tax": 2.1}]}],
    }), encoding="utf-8")
    s = storage.load(p)
    assert s.get_order(1001).channel == "web"
    assert reports.daily_sales(s, date(2026, 2, 10), channel="web").orders == 1


def test_cli_order_channel_and_show(tmp_path):
    data = tmp_path / "shop.json"
    storage.save(make_shop(), data)
    assert run_cli(data, "order", "MUG:2", "--customer", "Lee", "--channel", "phone").returncode == 0
    assert run_cli(data, "order", "BOOK", "--customer", "Kim").returncode == 0
    assert run_cli(data, "order", "BOOK", "--customer", "Kim", "--channel", "fax").returncode != 0
    out = run_cli(data, "show", "1001").stdout.splitlines()
    assert out[:6] == ["주문 1001 (pending)", "고객: Lee", "날짜: 2026-03-01 12:00", "지역: domestic", "채널: phone",
                       "  MUG  Mug  2 x 8.50 = 17.00"]
    out = run_cli(data, "show", "1002").stdout.splitlines()
    assert out[3:5] == ["지역: domestic", "  BOOK  Python Book  1 x 30.00 = 30.00"]
    assert not any(line.startswith("채널") for line in out)


def test_cli_orders_filter(tmp_path):
    s, a, b, c = scenario()
    s.checkout([("MUG", 1)], "Choi", channel="store")
    data = tmp_path / "shop.json"
    storage.save(s, data)
    assert run_cli(data, "orders", "--channel", "store").stdout.splitlines() == \
        [f"{c.id}\t2026-03-01\tPark\tpaid\t31.51", "1004\t2026-03-01\tChoi\tpending\t15.95"]
    assert run_cli(data, "orders", "--channel", "store", "--status", "pending").stdout.splitlines() == \
        ["1004\t2026-03-01\tChoi\tpending\t15.95"]
    assert len(run_cli(data, "orders").stdout.splitlines()) == 4


def test_cli_report_filters(tmp_path):
    s, a, b, c = scenario()
    data = tmp_path / "shop.json"
    storage.save(s, data)
    assert run_cli(data, "report", "daily", "2026-03-01", "--channel", "phone").stdout.splitlines()[1:3] == \
        ["orders\t1", "gross\t26.06"]
    assert run_cli(data, "report", "top", "--channel", "store").stdout.splitlines() == ["NOVEL\tNovel\t2"]
    assert run_cli(data, "report", "category", "2026-03-01", "2026-03-01", "--channel", "web").stdout.splitlines() == \
        ["books\t30.00"]
    assert run_cli(data, "report", "tax", "2026-03-01", "2026-03-01", "--channel", "store").stdout.splitlines() == \
        ["7%\t24.00\t1.68", "19%\t4.90\t0.93"]


def _read(path, delim):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f, delimiter=delim))


def test_csv_export_channel_column(tmp_path):
    s, a, b, c = scenario()
    csvio.export_orders(s, tmp_path / "o.csv")
    rows = _read(tmp_path / "o.csv", ",")
    assert rows[0] == ["order_id", "date", "customer", "status", "sku", "name", "qty", "unit_price", "discount", "net",
                       "tax", "channel"]
    assert [r[-1] for r in rows[1:]] == ["web", "phone", "store"]
    assert rows[2][:11] == [str(b.id), "2026-03-01", "Lee", "paid", "MUG", "Mug", "2", "8.50", "0.00", "17.00", "3.23"]


def test_csv_export_channel_eu_locale(tmp_path):
    s, a, b, c = scenario()
    s.settings.set("locale", "eu")
    csvio.export_orders(s, tmp_path / "o.csv")
    rows = _read(tmp_path / "o.csv", ";")
    assert rows[0][-1] == "channel" and len(rows[0]) == 12
    assert rows[2] == [str(b.id), "2026-03-01", "Lee", "paid", "MUG", "Mug", "2", "8,50", "0,00", "17,00", "3,23",
                       "phone"]
