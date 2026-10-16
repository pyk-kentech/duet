"""기존 동작 (예약 기능 추가 후에도 그대로여야 함)."""

import json
import subprocess
import sys
from datetime import datetime
from decimal import Decimal

import pytest

from stock import DuplicateItem, InsufficientStock, Inventory, StorageError, UnknownItem
from stock import storage

T = datetime(2026, 3, 1, 12, 0)


def inv():
    i = Inventory(clock=lambda: T)
    i.add_item("A-1", "Apple", "0.50")
    i.add_item("B-2", "Banana", "0.25")
    return i


def test_receive_ship_adjust_history():
    i = inv()
    i.receive("A-1", 10, "first")
    i.ship("A-1", 3)
    i.adjust("A-1", -2, " broken ")
    assert i.item("A-1").on_hand == 5
    h = i.history("A-1")
    assert [(m.kind, m.qty, m.note) for m in h] == [("receive", 10, "first"), ("ship", -3, ""), ("adjust", -2, "broken")]
    assert all(m.ts == T for m in h)
    assert i.history() == h


def test_ship_and_adjust_limits():
    i = inv()
    i.receive("A-1", 2)
    with pytest.raises(InsufficientStock):
        i.ship("A-1", 3)
    with pytest.raises(InsufficientStock):
        i.adjust("A-1", -3, "x")
    i.adjust("A-1", 5, "found")
    assert i.item("A-1").on_hand == 7


def test_value_low_items_sorted():
    i = inv()
    i.add_item("0-Z", "Zero")
    i.receive("A-1", 4)
    i.receive("B-2", 1)
    assert i.value() == Decimal("2.25")
    assert [x.sku for x in i.items()] == ["0-Z", "A-1", "B-2"]
    assert [x.sku for x in i.low_stock(1)] == ["0-Z", "B-2"]


@pytest.mark.parametrize("call", [
    lambda i: i.add_item("A-1", "again"),
])
def test_duplicate(call):
    with pytest.raises(DuplicateItem):
        call(inv())


@pytest.mark.parametrize("call", [
    lambda i: i.receive("NOPE", 1), lambda i: i.ship("NOPE", 1), lambda i: i.history("NOPE"),
])
def test_unknown(call):
    with pytest.raises(UnknownItem):
        call(inv())


@pytest.mark.parametrize("call", [
    lambda i: i.receive("A-1", 0), lambda i: i.receive("A-1", True), lambda i: i.ship("A-1", -1),
    lambda i: i.adjust("A-1", 0, "x"), lambda i: i.adjust("A-1", 1, "  "), lambda i: i.add_item("a-1", "x"),
    lambda i: i.add_item("C", " "), lambda i: i.add_item("C", "c", "-1"), lambda i: i.add_item("C", "c", "abc"),
])
def test_value_errors(call):
    with pytest.raises(ValueError):
        call(inv())


def test_storage_roundtrip(tmp_path):
    i = inv()
    i.receive("A-1", 3, "n")
    p = tmp_path / "s.json"
    storage.save(i, p)
    back = storage.load(p)
    assert [(x.sku, x.name, x.on_hand, x.unit_cost) for x in back.items()] == [
        ("A-1", "Apple", 3, Decimal("0.50")), ("B-2", "Banana", 0, Decimal("0.25"))]
    assert [(m.ts, m.kind, m.qty, m.note) for m in back.history()] == [(T, "receive", 3, "n")]
    assert not (tmp_path / "s.json.tmp").exists()


def test_storage_missing_and_corrupt(tmp_path):
    assert storage.load(tmp_path / "none.json").items() == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(StorageError):
        storage.load(bad)


def cli(tmp_path, *args):
    return subprocess.run([sys.executable, "-m", "stock", "--db", str(tmp_path / "s.json"), *args],
                          capture_output=True, text=True, timeout=30)


def test_cli_flow(tmp_path):
    assert cli(tmp_path, "add", "A-1", "Apple", "--cost", "0.50").returncode == 0
    assert cli(tmp_path, "receive", "A-1", "4", "--note", "po-1").returncode == 0
    assert cli(tmp_path, "ship", "A-1", "1").returncode == 0
    assert cli(tmp_path, "adjust", "A-1", "-1", "--reason", "count").returncode == 0
    assert cli(tmp_path, "value").stdout.strip() == "TOTAL\t1.00"
    lines = cli(tmp_path, "history", "A-1").stdout.splitlines()
    assert [ln.split("\t")[2:] for ln in lines] == [["receive", "4", "po-1"], ["ship", "-1", ""], ["adjust", "-1", "count"]]


def test_cli_errors(tmp_path):
    assert cli(tmp_path, "add", "A-1", "Apple").returncode == 0
    for args in (["ship", "A-1", "1"], ["receive", "NOPE", "1"], ["add", "A-1", "dup"], ["adjust", "A-1", "1", "--reason", " "]):
        r = cli(tmp_path, *args)
        assert r.returncode == 1 and r.stderr.startswith("오류:"), args
    data = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert [x["sku"] for x in data["items"]] == ["A-1"]
