import os
import subprocess
import sys
from datetime import datetime

import pytest

from shop import Shop

T0 = datetime(2026, 3, 1, 12, 0)


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def shop(clock):
    s = Shop(clock=clock)
    s.add_product("BOOK", "Python Book", "books", "30.00", weight_g=800)
    s.add_product("MUG", "Mug", "home", "8.50", weight_g=350)
    s.add_product("TEA", "Green Tea", "food", "4.20", weight_g=100, tiers="10:5,50:10")
    s.add_product("TSHIRT", "T-Shirt", "apparel", "19.99", weight_g=200, tiers="10:10")
    s.add_variant("TSHIRT", "TSHIRT-M", attrs={"color": "red", "size": "M"})
    s.add_variant("TSHIRT", "TSHIRT-L", attrs={"color": "red", "size": "L"}, price="21.99")
    for sku in ("BOOK", "MUG", "TEA", "TSHIRT-M", "TSHIRT-L"):
        s.receive(sku, 100)
    return s


@pytest.fixture
def cli(tmp_path):
    data = tmp_path / "shop.json"

    def run(*args, now="2026-03-01T12:00:00"):
        env = dict(os.environ, SHOP_NOW=now, PYTHONIOENCODING="utf-8")
        return subprocess.run([sys.executable, "-m", "shop", "--data", str(data), *args], capture_output=True,
                              text=True, encoding="utf-8", env=env)

    run.data = data
    return run
