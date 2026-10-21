"""티켓 3: 주문이 취소되면 쓴 쿠폰의 사용 횟수를 돌려준다."""

import os
import subprocess
import sys
from datetime import datetime, timedelta

from shop import Shop
from shop import storage

T0 = datetime(2026, 3, 1, 12, 0)


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


def make_shop(clock=None):
    s = Shop(clock=clock or Clock())
    s.add_product("BOOK", "Python Book", "books", "30.00", weight_g=800)
    s.add_product("MUG", "Mug", "home", "8.50", weight_g=350)
    for sku in ("BOOK", "MUG"):
        s.receive(sku, 100)
    return s


def run_cli(data, *args, now="2026-03-01T12:00:00"):
    env = dict(os.environ, SHOP_NOW=now, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "shop", "--data", str(data), *args], capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=60)


def test_cancel_pending_returns_use():
    s = make_shop()
    s.add_coupon("SAVE10", "percent", "10")
    o = s.checkout([("BOOK", 1)], "Kim", coupons=["SAVE10"])
    assert s.coupon("SAVE10").uses == 1
    s.cancel(o.id)
    assert s.coupon("SAVE10").uses == 0


def test_cancel_paid_returns_use():
    s = make_shop()
    s.add_coupon("SAVE10", "percent", "10")
    s.checkout([("MUG", 1)], "Lee", coupons=["SAVE10"])
    o = s.checkout([("BOOK", 1)], "Kim", coupons=["SAVE10"])
    s.pay(o.id)
    s.cancel(o.id)
    assert s.coupon("SAVE10").uses == 1


def test_single_use_coupon_usable_again_after_cancel():
    s = make_shop()
    s.add_coupon("ONCE", "fixed", "5", max_uses=1)
    o = s.checkout([("BOOK", 1)], "Kim", coupons=["ONCE"])
    s.cancel(o.id)
    o2 = s.checkout([("BOOK", 1)], "Kim", coupons=["ONCE"])
    assert o2.coupons == ["ONCE"] and s.coupon("ONCE").uses == 1


def test_expire_pending_returns_use():
    clock = Clock()
    s = make_shop(clock)
    s.add_coupon("ONCE", "fixed", "5", max_uses=1)
    s.add_coupon("SAVE10", "percent", "10")
    old = s.checkout([("BOOK", 1)], "Kim", coupons=["ONCE"])
    clock.t += timedelta(hours=30)
    young = s.checkout([("BOOK", 1)], "Lee", coupons=["SAVE10"])
    clock.t += timedelta(hours=1)
    assert s.expire_pending(timedelta(hours=24)) == [old.id]
    assert s.coupon("ONCE").uses == 0 and s.coupon("SAVE10").uses == 1
    assert young.status == "pending"


def test_expire_several_orders_with_same_coupon():
    clock = Clock()
    s = make_shop(clock)
    s.add_coupon("SAVE10", "percent", "10", max_uses=3)
    s.add_coupon("SHIP", "free_shipping")
    for name in ("Kim", "Lee", "Park"):
        s.checkout([("MUG", 1)], name, coupons=["SAVE10", "SHIP"])
    assert s.coupon("SAVE10").uses == 3
    clock.t += timedelta(days=2)
    assert s.expire_pending(timedelta(hours=24)) == [1001, 1002, 1003]
    assert s.coupon("SAVE10").uses == 0 and s.coupon("SHIP").uses == 0
    assert len(s.checkout([("MUG", 1)], "Choi", coupons=["SAVE10"]).coupons) == 1


def test_expire_skips_paid_and_young_orders():
    clock = Clock()
    s = make_shop(clock)
    s.add_coupon("SAVE10", "percent", "10")
    paid = s.checkout([("BOOK", 1)], "Kim", coupons=["SAVE10"])
    s.pay(paid.id)
    old = s.checkout([("MUG", 1)], "Lee", coupons=["SAVE10"])
    clock.t += timedelta(hours=23)
    s.checkout([("MUG", 1)], "Park", coupons=["SAVE10"])
    clock.t += timedelta(hours=2)
    assert s.coupon("SAVE10").uses == 3
    assert s.expire_pending(timedelta(hours=24)) == [old.id]
    assert s.coupon("SAVE10").uses == 2


def test_every_coupon_of_the_order_returned():
    s = make_shop()
    s.add_coupon("AAA", "percent", "10", stackable=True)
    s.add_coupon("BBB", "fixed", "2", stackable=True)
    s.add_coupon("SHIP", "free_shipping")
    o = s.checkout([("BOOK", 1), ("MUG", 1)], "Kim", coupons=["AAA", "BBB", "SHIP"])
    s.cancel(o.id)
    assert [c.uses for c in s.coupons_list()] == [0, 0, 0]


def test_removed_coupon_ignored():
    s = make_shop()
    s.add_coupon("GONE", "percent", "10")
    s.add_coupon("KEEP", "free_shipping")
    o = s.checkout([("BOOK", 1)], "Kim", coupons=["GONE", "KEEP"])
    s.remove_coupon("GONE")
    s.cancel(o.id)
    assert o.status == "cancelled" and s.coupon("KEEP").uses == 0 and "GONE" not in s.coupons


def test_uses_never_below_zero():
    s = make_shop()
    s.add_coupon("RESET", "percent", "10")
    o = s.checkout([("BOOK", 1)], "Kim", coupons=["RESET"])
    s.remove_coupon("RESET")
    s.add_coupon("RESET", "percent", "10")        # 다시 만든 쿠폰: uses 0
    s.cancel(o.id)
    assert s.coupon("RESET").uses == 0


def test_cli_cancel_returns_use(tmp_path):
    data = tmp_path / "shop.json"
    storage.save(make_shop(), data)
    run_cli(data, "coupon-add", "ONCE", "fixed", "5", "--max-uses", "1")
    run_cli(data, "order", "BOOK", "--customer", "Kim", "--coupon", "once")
    assert run_cli(data, "coupons").stdout.splitlines() == ["ONCE\tfixed\t5.00\t1/1"]
    assert run_cli(data, "cancel", "1001").returncode == 0
    assert run_cli(data, "coupons").stdout.splitlines() == ["ONCE\tfixed\t5.00\t0/1"]
    assert run_cli(data, "order", "BOOK", "--customer", "Lee", "--coupon", "ONCE").returncode == 0


def test_cli_expire_pending_returns_use(tmp_path):
    data = tmp_path / "shop.json"
    storage.save(make_shop(), data)
    run_cli(data, "coupon-add", "ONCE", "fixed", "5", "--max-uses", "1")
    run_cli(data, "order", "BOOK", "--customer", "Kim", "--coupon", "ONCE")
    r = run_cli(data, "expire-pending", "--hours", "24", now="2026-03-03T12:00:00")
    assert r.stdout.strip() == "취소: 1001"
    assert run_cli(data, "coupons").stdout.splitlines() == ["ONCE\tfixed\t5.00\t0/1"]
