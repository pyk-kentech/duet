"""다중 창고 (새 기능)."""

import json
import subprocess
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from stock import (
    DuplicateWarehouse, InsufficientStock, Inventory, Item, Movement, StockError, StorageError, UnknownItem,
    UnknownWarehouse, WarehouseNotEmpty,
)
from stock import reports, storage

T = datetime(2026, 3, 1, 12, 0)


class Clock:
    def __init__(self):
        self.t = T

    def __call__(self):
        return self.t


def inv(clock=None):
    i = Inventory(clock=clock or (lambda: T))
    i.add_item("A-1", "Apple", "0.50")
    i.add_item("B-2", "Banana", "0.25")
    i.add_warehouse("EAST", " East side ")
    return i


def test_errors_are_stock_errors():
    for e in (UnknownWarehouse, DuplicateWarehouse, WarehouseNotEmpty):
        assert issubclass(e, StockError)


def test_main_exists_and_add_warehouse():
    i = Inventory(clock=lambda: T)
    assert [(w.code, w.name) for w in i.warehouses()] == [("MAIN", "Main")]
    i.add_warehouse("W2", "Second")
    i.add_warehouse("A1", "First")
    assert [w.code for w in i.warehouses()] == ["A1", "MAIN", "W2"]
    with pytest.raises(DuplicateWarehouse):
        i.add_warehouse("W2", "again")
    with pytest.raises(DuplicateWarehouse):
        i.add_warehouse("MAIN", "again")


@pytest.mark.parametrize("code, name", [("east", "x"), ("1A", "x"), ("ABCDEFGHI", "x"), ("A-1", "x"), ("", "x"), ("NEW", "  ")])
def test_add_warehouse_validation(code, name):
    with pytest.raises(ValueError):
        Inventory(clock=lambda: T).add_warehouse(code, name)


def test_name_stripped():
    assert [w.name for w in inv().warehouses() if w.code == "EAST"] == ["East side"]


def test_per_warehouse_stock_and_total():
    i = inv()
    i.receive("A-1", 5)
    i.receive("A-1", 3, "po", warehouse="EAST")
    assert i.item("A-1").on_hand == 8 and i.on_hand("A-1") == 8
    assert i.on_hand("A-1", "MAIN") == 5 and i.on_hand("A-1", "EAST") == 3
    assert i.stock_by_warehouse("A-1") == {"EAST": 3, "MAIN": 5}
    assert list(i.stock_by_warehouse("B-2").items()) == [("EAST", 0), ("MAIN", 0)]
    assert i.value() == Decimal("4.00")


def test_ship_limited_by_that_warehouse():
    i = inv()
    i.receive("A-1", 5)
    i.receive("A-1", 3, warehouse="EAST")
    with pytest.raises(InsufficientStock):
        i.ship("A-1", 4, warehouse="EAST")       # 합계 8 이어도 EAST 는 3
    i.ship("A-1", 3, warehouse="EAST")
    assert i.on_hand("A-1", "EAST") == 0 and i.item("A-1").on_hand == 5
    assert i.history("A-1")[-1].warehouse == "EAST"


def test_adjust_limited_by_that_warehouse():
    i = inv()
    i.receive("A-1", 5)
    i.receive("A-1", 1, warehouse="EAST")
    with pytest.raises(InsufficientStock):
        i.adjust("A-1", -2, "lost", warehouse="EAST")
    i.adjust("A-1", -1, "lost", warehouse="EAST")
    i.adjust("A-1", 2, "found", warehouse="EAST")
    assert i.stock_by_warehouse("A-1") == {"EAST": 2, "MAIN": 5}
    assert i.item("A-1").on_hand == 7


def test_failed_operations_change_nothing():
    i = inv()
    i.receive("A-1", 2, warehouse="EAST")
    for call in (lambda: i.ship("A-1", 3, warehouse="EAST"), lambda: i.transfer("A-1", 3, "EAST", "MAIN"),
                 lambda: i.adjust("A-1", -3, "x", warehouse="EAST")):
        with pytest.raises(InsufficientStock):
            call()
    assert i.stock_by_warehouse("A-1") == {"EAST": 2, "MAIN": 0} and i.item("A-1").on_hand == 2
    assert len(i.history()) == 1


@pytest.mark.parametrize("call", [
    lambda i: i.receive("A-1", 1, warehouse="WEST"), lambda i: i.ship("A-1", 1, warehouse="WEST"),
    lambda i: i.adjust("A-1", 1, "x", warehouse="WEST"), lambda i: i.on_hand("A-1", "WEST"),
    lambda i: i.history(warehouse="WEST"), lambda i: i.transfer("A-1", 1, "MAIN", "WEST"),
    lambda i: i.transfer("A-1", 1, "WEST", "MAIN"), lambda i: i.remove_warehouse("WEST"),
])
def test_unknown_warehouse(call):
    with pytest.raises(UnknownWarehouse):
        call(inv())


def test_unknown_item_still_unknown_item():
    with pytest.raises(UnknownItem):
        inv().on_hand("NOPE", "MAIN")
    with pytest.raises(UnknownItem):
        inv().stock_by_warehouse("NOPE")


def test_transfer_moves_and_records():
    c = Clock()
    i = inv(c)
    i.receive("A-1", 6)
    c.t += timedelta(minutes=5)
    i.transfer("A-1", 4, "MAIN", "EAST", "rebalance")
    assert i.stock_by_warehouse("A-1") == {"EAST": 4, "MAIN": 2} and i.item("A-1").on_hand == 6
    out, inn = i.history("A-1")[-2:]
    assert (out.kind, out.qty, out.warehouse, out.note) == ("transfer-out", -4, "MAIN", "rebalance")
    assert (inn.kind, inn.qty, inn.warehouse, inn.note) == ("transfer-in", 4, "EAST", "rebalance")
    assert out.ts == inn.ts == c.t
    assert i.value() == Decimal("3.00")


@pytest.mark.parametrize("args", [("A-1", 0, "MAIN", "EAST"), ("A-1", True, "MAIN", "EAST"), ("A-1", 1, "MAIN", "MAIN")])
def test_transfer_value_errors(args):
    i = inv()
    i.receive("A-1", 5)
    with pytest.raises(ValueError):
        i.transfer(*args)


def test_history_filter_by_warehouse():
    i = inv()
    i.receive("A-1", 2)
    i.receive("B-2", 2, warehouse="EAST")
    i.transfer("A-1", 1, "MAIN", "EAST")
    assert [(m.sku, m.kind) for m in i.history(warehouse="EAST")] == [("B-2", "receive"), ("A-1", "transfer-in")]
    assert [m.kind for m in i.history("A-1", warehouse="MAIN")] == ["receive", "transfer-out"]


def test_remove_warehouse_rules():
    i = inv()
    with pytest.raises(ValueError):
        i.remove_warehouse("MAIN")
    i.receive("A-1", 1, warehouse="EAST")
    with pytest.raises(WarehouseNotEmpty):
        i.remove_warehouse("EAST")
    i.transfer("A-1", 1, "EAST", "MAIN")
    i.remove_warehouse("EAST")
    assert [w.code for w in i.warehouses()] == ["MAIN"]
    assert any(m.warehouse == "EAST" for m in i.history())        # 기록은 남는다
    assert i.stock_by_warehouse("A-1") == {"MAIN": 1}


def test_movement_positional_and_default():
    m = Movement(T, "A-1", "receive", 1, "n")
    assert m.warehouse == "MAIN"


def test_constructor_items_on_hand_go_to_main():
    i = Inventory([Item("A-1", "Apple", 7, Decimal("1"))], clock=lambda: T)
    assert i.on_hand("A-1", "MAIN") == 7 and i.item("A-1").on_hand == 7
    i.add_warehouse("EAST", "E")
    i.transfer("A-1", 2, "MAIN", "EAST")
    assert i.item("A-1").on_hand == 7


def test_low_stock_still_total():
    i = inv()
    i.receive("A-1", 1)
    i.receive("A-1", 1, warehouse="EAST")
    assert [x.sku for x in i.low_stock(1)] == ["B-2"]


# ---------------------------------------------------------------- reports
def test_low_stock_by_warehouse():
    i = inv()
    i.add_warehouse("CENT", "Center")
    i.receive("A-1", 5)
    i.receive("B-2", 2, warehouse="EAST")
    assert reports.low_stock_by_warehouse(i, 1) == [
        ("CENT", "A-1", 0), ("CENT", "B-2", 0), ("EAST", "A-1", 0), ("MAIN", "B-2", 0)]
    assert ("EAST", "B-2", 2) in reports.low_stock_by_warehouse(i, 2)


def test_movements_summary_window():
    c = Clock()
    i = inv(c)
    i.receive("A-1", 10)
    c.t += timedelta(hours=1)
    i.transfer("A-1", 4, "MAIN", "EAST")
    i.ship("A-1", 1, warehouse="EAST")
    i.ship("A-1", 2)
    c.t += timedelta(hours=1)
    i.receive("B-2", 3, warehouse="EAST")
    got = reports.movements_summary(i, T + timedelta(minutes=30), T + timedelta(hours=2))
    assert got == {"EAST": {"ship": -1, "transfer-in": 4}, "MAIN": {"ship": -2, "transfer-out": -4}}
    assert list(got) == ["EAST", "MAIN"] and list(got["MAIN"]) == ["ship", "transfer-out"]
    assert reports.movements_summary(i, T, T) == {}


# ---------------------------------------------------------------- storage
def test_storage_v2_roundtrip(tmp_path):
    c = Clock()
    i = inv(c)
    i.receive("A-1", 5)
    i.transfer("A-1", 2, "MAIN", "EAST", "move")
    p = tmp_path / "s.json"
    storage.save(i, p)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["version"] == 2
    assert {w["code"] for w in data["warehouses"]} == {"MAIN", "EAST"}
    assert all("on_hand" not in x for x in data["items"])
    back = storage.load(p)
    assert [(w.code, w.name) for w in back.warehouses()] == [("EAST", "East side"), ("MAIN", "Main")]
    assert back.stock_by_warehouse("A-1") == {"EAST": 2, "MAIN": 3} and back.item("A-1").on_hand == 5
    assert [(m.kind, m.qty, m.warehouse) for m in back.history()] == [
        ("receive", 5, "MAIN"), ("transfer-out", -2, "MAIN"), ("transfer-in", 2, "EAST")]


def test_storage_reads_v1(tmp_path):
    p = tmp_path / "old.json"
    p.write_text(json.dumps({"version": 1, "items": [{"sku": "A-1", "name": "Apple", "on_hand": 4, "unit_cost": "0.50"}],
                             "movements": [{"ts": T.isoformat(), "sku": "A-1", "kind": "receive", "qty": 4, "note": ""}]}),
                 encoding="utf-8")
    i = storage.load(p)
    assert i.on_hand("A-1", "MAIN") == 4 and [w.code for w in i.warehouses()] == ["MAIN"]
    assert i.history()[0].warehouse == "MAIN"
    storage.save(i, p)
    assert json.loads(p.read_text(encoding="utf-8"))["version"] == 2


@pytest.mark.parametrize("data", [
    {"version": 3, "items": []},
    {"version": 2, "warehouses": [{"code": "MAIN", "name": "Main"}],
     "items": [{"sku": "A-1", "name": "A", "stock": {"WEST": 1}, "unit_cost": "1"}], "movements": []},
    {"version": 2, "warehouses": [{"code": "MAIN", "name": "Main"}], "items": [],
     "movements": [{"ts": T.isoformat(), "sku": "A-1", "kind": "receive", "qty": 1, "note": "", "warehouse": "WEST"}]},
])
def test_storage_rejects(tmp_path, data):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(StorageError):
        storage.load(p)


# ---------------------------------------------------------------- CLI
def cli(tmp_path, *args):
    return subprocess.run([sys.executable, "-m", "stock", "--db", str(tmp_path / "s.json"), *args],
                          capture_output=True, text=True, timeout=30)


def test_cli_warehouse_flow(tmp_path):
    assert cli(tmp_path, "add", "A-1", "Apple", "--cost", "1").returncode == 0
    assert cli(tmp_path, "wh-add", "EAST", "East").returncode == 0
    assert cli(tmp_path, "receive", "A-1", "5").returncode == 0
    assert cli(tmp_path, "receive", "A-1", "2", "--wh", "EAST").returncode == 0
    assert cli(tmp_path, "transfer", "A-1", "1", "MAIN", "EAST", "--note", "mv").returncode == 0
    assert cli(tmp_path, "where", "A-1").stdout.splitlines() == ["EAST\t3", "MAIN\t4"]
    assert cli(tmp_path, "warehouses").stdout.splitlines() == ["EAST\tEast\t3", "MAIN\tMain\t4"]
    assert cli(tmp_path, "list").stdout.splitlines() == ["A-1\tApple\t7"]
    assert cli(tmp_path, "list", "--wh", "EAST").stdout.splitlines() == ["A-1\tApple\t3"]
    hist = cli(tmp_path, "history", "--wh", "EAST").stdout.splitlines()
    assert [ln.split("\t")[2:] for ln in hist] == [["receive", "2", ""], ["transfer-in", "1", "mv"]]
    assert cli(tmp_path, "ship", "A-1", "3", "--wh", "EAST").returncode == 0
    assert cli(tmp_path, "adjust", "A-1", "1", "--reason", "found", "--wh", "EAST").returncode == 0
    assert cli(tmp_path, "where", "A-1").stdout.splitlines() == ["EAST\t1", "MAIN\t4"]


def test_cli_errors_keep_file(tmp_path):
    cli(tmp_path, "add", "A-1", "Apple")
    cli(tmp_path, "wh-add", "EAST", "East")
    cli(tmp_path, "receive", "A-1", "1", "--wh", "EAST")
    before = (tmp_path / "s.json").read_text(encoding="utf-8")
    for args in (["ship", "A-1", "2", "--wh", "EAST"], ["receive", "A-1", "1", "--wh", "WEST"], ["wh-rm", "EAST"],
                 ["wh-rm", "MAIN"], ["wh-add", "east", "x"], ["transfer", "A-1", "1", "EAST", "EAST"],
                 ["list", "--wh", "WEST"], ["where", "NOPE"]):
        r = cli(tmp_path, *args)
        assert r.returncode == 1 and r.stderr.startswith("오류:"), (args, r.stderr)
    assert (tmp_path / "s.json").read_text(encoding="utf-8") == before


def test_cli_wh_rm(tmp_path):
    cli(tmp_path, "wh-add", "TMP", "Temp")
    assert cli(tmp_path, "wh-rm", "TMP").returncode == 0
    assert cli(tmp_path, "warehouses").stdout.splitlines() == ["MAIN\tMain\t0"]
