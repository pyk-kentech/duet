"""티켓 8: 주문 5만·환불 1만 건에서도 보고서·주문 조회가 빨라야 한다.

데이터는 README/DESIGN.md 의 버전 2 형식으로 만든다. 측정은 별도 프로세스에서 하고, 느린 구현이
채점 시간을 다 쓰지 않게 프로세스마다 시간 제한을 둔다(제한은 참조 구현 시간의 5배를 훌쩍 넘는다).
"""

import json
import os
import random
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal as D

import pytest

N_ORDERS = 50_000
N_PENDING = 10_000          # 번호가 가장 큰 1만 건 (1월에 만든 미결제 주문)
N_MARCH = N_ORDERS - N_PENDING
PROCESS_TIMEOUT = 20
PRICES = ["10.00", "12.50", "4.20", "8.99", "25.00", "3.33"]
CATEGORIES = ["books", "home", "food"]
RATES = {"books": D("7"), "home": D("19"), "food": D("7")}
DAY = date(2026, 3, 15)
START, END = date(2026, 3, 1), date(2026, 3, 31)


def money(x):
    return x.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def build():
    products = [{"sku": f"P{i:03d}", "name": f"Product {i}", "category": CATEGORIES[i % 3],
                 "price": float(PRICES[i % len(PRICES)]), "weight_g": 100, "tiers": [], "active": True}
                for i in range(30)]
    orders, refunds, reserved = [], [], {}
    exp = {"daily": [0, D(0), D(0), D(0)], "cat": {}, "sold": {}, "names": {}, "tax": {}}

    def tax_add(rate, net, tax):
        row = exp["tax"].setdefault(rate, [D(0), D(0)])
        row[0] += net
        row[1] += tax

    refund_id = 1
    for k in range(N_ORDERS):
        oid = 1001 + k
        j = k
        if k >= N_MARCH:
            created = datetime(2026, 1, 5, 10, 0) + timedelta(days=k % 20)
            status = "pending"
        else:
            if j < 30_000:
                created = datetime(2026, 3, 15, 8, 0) + timedelta(seconds=j)
            else:
                created = datetime(2026, 3, 1, 9, 0) + timedelta(days=j % 31)
            status = "shipped" if j % 2 == 0 else "paid"
        lines = []
        for n in range(3):
            p = products[(k * 7 + n) % 30]
            qty = 1 if n == 0 else 1 + (k + n) % 3
            price = D(PRICES[((k * 7 + n) % 30) % len(PRICES)])
            rate = RATES[p["category"]]
            lines.append({"sku": p["sku"], "name": p["name"], "category": p["category"], "qty": qty,
                          "list_price": float(price), "unit_price": float(price), "discount": 0.0,
                          "tax_rate": float(rate), "tax": float(money(price * qty * rate / 100)),
                          "_net": price * qty, "_tax": money(price * qty * rate / 100), "_rate": rate})
        subtotal = sum(ln["_net"] for ln in lines)
        shipping, shipping_tax = (D("0.00"), D("0.00")) if subtotal >= 50 else (D("4.90"), D("0.93"))
        total = subtotal + shipping + sum(ln["_tax"] for ln in lines) + shipping_tax
        order_refunds = []
        if status != "pending" and j % 4 == 1:
            first = lines[0]
            order_refunds.append({"id": refund_id, "order_id": oid, "created": (created + timedelta(days=1)).isoformat(),
                                  "items": {first["sku"]: 1}, "net": float(first["_net"]), "shipping": 0.0,
                                  "tax": float(first["_tax"]), "reason": "",
                                  "_amount": first["_net"] + first["_tax"], "_tax": first["_tax"]})
            refund_id += 1
        if status == "pending":
            for ln in lines:
                reserved[ln["sku"]] = reserved.get(ln["sku"], 0) + ln["qty"]
        elif START <= created.date() <= END:
            for ln in lines:
                exp["cat"][ln["category"]] = exp["cat"].get(ln["category"], D(0)) + ln["_net"]
                exp["sold"][ln["sku"]] = exp["sold"].get(ln["sku"], 0) + ln["qty"]
                exp["names"].setdefault(ln["sku"], ln["name"])
                tax_add(ln["_rate"], ln["_net"], ln["_tax"])
            if shipping:
                tax_add(D("19"), shipping, shipping_tax)
            for r in order_refunds:
                first = lines[0]
                exp["cat"][first["category"]] -= first["_net"]
                exp["sold"][first["sku"]] -= 1
                tax_add(first["_rate"], -first["_net"], -first["_tax"])
            if created.date() == DAY:
                d = exp["daily"]
                d[0] += 1
                d[1] += total
                d[2] += sum(r["_amount"] for r in order_refunds)
                d[3] += sum(ln["_tax"] for ln in lines) + shipping_tax - sum(r["_tax"] for r in order_refunds)
        orders.append({"id": oid, "created": created.isoformat(), "customer": f"Customer {k % 997}",
                       "region": "domestic", "status": status, "coupons": [], "shipping": float(shipping),
                       "shipping_tax": float(shipping_tax), "paid_at": None if status == "pending" else created.isoformat(),
                       "shipped_at": created.isoformat() if status == "shipped" else None,
                       "lines": [{k2: v for k2, v in ln.items() if not k2.startswith("_")} for ln in lines]})
        refunds += [{k2: v for k2, v in r.items() if not k2.startswith("_")} for r in order_refunds]
    data = {"version": 2, "settings": {"locale": "default", "tax_display": "exclusive"},
            "tax": {"default": 19.0, "rates": {"books": 7.0, "food": 7.0}},
            "products": products, "variants": [],
            "stock": {"on_hand": {p["sku"]: 1_000_000 for p in products}, "reserved": reserved},
            "coupons": [], "orders": orders, "refunds": refunds,
            "next_order_id": 1001 + N_ORDERS, "next_refund_id": refund_id}
    expected = {
        "daily": [exp["daily"][0], str(exp["daily"][1]), str(exp["daily"][2]), str(exp["daily"][1] - exp["daily"][2]),
                  str(exp["daily"][3])],
        "category": {k: str(v) for k, v in sorted(exp["cat"].items())},
        "top": [[s, exp["names"][s], q] for s, q in sorted(exp["sold"].items(), key=lambda t: (-t[1], t[0]))
                if q > 0][:5],
        "tax": [[str(rate), str(v[0]), str(v[1])] for rate, v in sorted(exp["tax"].items())],
    }
    return data, expected, refund_id - 1


SCRIPT = r'''
import json, sys, time
from datetime import date, datetime, timedelta
from shop import reports, storage

path, op = sys.argv[1], sys.argv[2]
shop = storage.load(path, clock=lambda: datetime(2026, 4, 1, 12, 0))
day, start, end = date(2026, 3, 15), date(2026, 3, 1), date(2026, 3, 31)

t = time.perf_counter()
if op == "daily":
    r = reports.daily_sales(shop, day)
    res = [r.orders, str(r.gross), str(r.refunds), str(r.net), str(r.tax)]
elif op == "category":
    res = {k: str(v) for k, v in reports.sales_by_category(shop, start, end).items()}
elif op == "top":
    res = [list(x) for x in reports.top_products(shop, 5, start, end)]
elif op == "tax":
    res = [[str(a), str(b), str(c)] for a, b, c in reports.tax_report(shop, start, end)]
elif op == "get_order":
    import random
    rng = random.Random(7)
    ids = [rng.randint(1001, 51000) for _ in range(10000)]
    t = time.perf_counter()
    res = sum(shop.get_order(i).id for i in ids)
elif op == "refunds":
    targets = [1001 + j for j in range(40000) if j % 4 == 3][-1000:]
    items = [(oid, shop.get_order(oid).lines[0].sku) for oid in targets]
    before = len(shop.refunds)
    t = time.perf_counter()
    for oid, sku in items:
        shop.refund(oid, {sku: 1})
    res = len(shop.refunds) - before
elif op == "expire":
    res = len(shop.expire_pending(timedelta(hours=24)))
elapsed = time.perf_counter() - t
print(json.dumps({"elapsed": elapsed, "result": res}))
'''


def _dec(x):
    return str(D(x).normalize())


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    d = tmp_path_factory.mktemp("perf")
    data, expected, n_refunds = build()
    assert n_refunds == 10_000 and len(data["orders"]) == N_ORDERS
    path = d / "big.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    script = d / "measure.py"
    script.write_text(SCRIPT, encoding="utf-8")
    return path, script, expected


def measure(big, op):
    path, script, _ = big
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run([sys.executable, str(script), str(path), op], capture_output=True, text=True,
                           encoding="utf-8", env=env, timeout=PROCESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        pytest.fail(f"{op}: {PROCESS_TIMEOUT}초 안에 끝나지 않음")
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def _same_money(got, want):
    return [_dec(x) for x in got] == [_dec(x) for x in want]


def test_daily_sales_fast(big):
    m = measure(big, "daily")
    want = big[2]["daily"]
    assert m["result"][0] == want[0] and _same_money(m["result"][1:], want[1:])
    assert m["elapsed"] < 2.0, m["elapsed"]


def test_sales_by_category_fast(big):
    m = measure(big, "category")
    want = big[2]["category"]
    assert list(m["result"]) == list(want) and _same_money(m["result"].values(), want.values())
    assert m["elapsed"] < 2.0, m["elapsed"]


def test_top_products_fast(big):
    m = measure(big, "top")
    assert m["result"] == big[2]["top"]
    assert m["elapsed"] < 2.0, m["elapsed"]


def test_tax_report_fast(big):
    m = measure(big, "tax")
    want = big[2]["tax"]
    assert len(m["result"]) == len(want)
    for got, exp in zip(m["result"], want):
        assert _same_money(got, exp)
    assert m["elapsed"] < 2.0, m["elapsed"]


def test_get_order_fast(big):
    m = measure(big, "get_order")
    rng = random.Random(7)
    assert m["result"] == sum(rng.randint(1001, 51000) for _ in range(10000))
    assert m["elapsed"] < 1.0, m["elapsed"]


def test_refunds_fast(big):
    m = measure(big, "refunds")
    assert m["result"] == 1000
    assert m["elapsed"] < 1.0, m["elapsed"]


def test_expire_pending_fast(big):
    m = measure(big, "expire")
    assert m["result"] == N_PENDING
    assert m["elapsed"] < 2.0, m["elapsed"]


def test_cli_report_fast(big):
    path, _, expected = big
    env = dict(os.environ, PYTHONIOENCODING="utf-8", SHOP_NOW="2026-04-01T12:00:00")
    t = time.perf_counter()
    try:
        r = subprocess.run([sys.executable, "-m", "shop", "--data", str(path), "report", "category", "2026-03-01",
                            "2026-03-31"], capture_output=True, text=True, encoding="utf-8", env=env,
                           timeout=PROCESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        pytest.fail(f"report category: {PROCESS_TIMEOUT}초 안에 끝나지 않음")
    elapsed = time.perf_counter() - t
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout.splitlines() == [f"{k}\t{D(v):.2f}" for k, v in expected["category"].items()]
    assert elapsed < 10.0, elapsed
