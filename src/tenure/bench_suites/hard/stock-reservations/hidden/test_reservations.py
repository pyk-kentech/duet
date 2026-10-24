"""예약 기능."""

import json
import subprocess
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

import stock
from stock import InsufficientStock, Inventory, StockError, StorageError, UnknownItem
from stock import storage

T0 = datetime(2026, 3, 1, 12, 0)
H = timedelta(hours=1)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


def setup():
    c = Clock()
    i = Inventory(clock=c)
    i.add_item("A-1", "Apple", "0.50")
    i.add_item("B-2", "Banana", "0.25")
    i.receive("A-1", 10)
    return i, c


def test_errors_exported():
    assert issubclass(stock.DuplicateReservation, StockError)
    assert issubclass(stock.ReservationNotFound, StockError)


def test_reserve_reduces_available_not_on_hand():
    i, _ = setup()
    moves = len(i.history())
    i.reserve("A-1", 4, "O1", T0 + H)
    assert i.available("A-1") == 6 and i.item("A-1").on_hand == 10
    assert len(i.history()) == moves                     # 예약은 이동 기록이 아니다
    assert i.value() == Decimal("5.00")                  # 금액은 on_hand 기준
    assert i.available("B-2") == 0


def test_reserve_up_to_available():
    i, _ = setup()
    i.reserve("A-1", 6, "O1", T0 + H)
    with pytest.raises(InsufficientStock):
        i.reserve("A-1", 5, "O2", T0 + H)
    i.reserve("A-1", 4, "O2", T0 + H)
    assert i.available("A-1") == 0


def test_expiry_boundary():
    i, c = setup()
    i.reserve("A-1", 4, "O1", T0 + H)
    c.now = T0 + H - timedelta(microseconds=1)
    assert i.available("A-1") == 6 and len(i.reservations()) == 1
    c.now = T0 + H                                       # 만료 시각과 같으면 무효
    assert i.available("A-1") == 10 and i.reservations() == []
    with pytest.raises(stock.ReservationNotFound):
        i.release("O1")
    with pytest.raises(stock.ReservationNotFound):
        i.fulfill("O1")


def test_duplicate_order_id_only_while_active():
    i, c = setup()
    i.reserve("A-1", 1, "O1", T0 + H)
    with pytest.raises(stock.DuplicateReservation):
        i.reserve("A-1", 1, "O1", T0 + 2 * H)
    c.now = T0 + 2 * H
    i.reserve("A-1", 2, "O1", T0 + 3 * H)                # 만료된 것과 번호가 같아도 된다
    assert i.available("A-1") == 8


@pytest.mark.parametrize("args,exc", [
    (("A-1", 0, "O1", T0 + H), ValueError),
    (("A-1", True, "O1", T0 + H), ValueError),
    (("A-1", 1, "", T0 + H), ValueError),
    (("A-1", 1, "O1", T0), ValueError),                 # 지금과 같은 만료는 안 됨
    (("A-1", 1, "O1", T0 - H), ValueError),
    (("NOPE", 1, "O1", T0 + H), UnknownItem),
])
def test_reserve_validation(args, exc):
    i, _ = setup()
    with pytest.raises(exc):
        i.reserve(*args)


def test_ship_respects_reservations():
    i, c = setup()
    i.reserve("A-1", 7, "O1", T0 + H)
    with pytest.raises(InsufficientStock):
        i.ship("A-1", 4)
    i.ship("A-1", 3)
    assert i.item("A-1").on_hand == 7 and i.available("A-1") == 0
    c.now = T0 + H
    i.ship("A-1", 7)                                     # 만료 후에는 전부 출고 가능
    assert i.item("A-1").on_hand == 0


def test_adjust_not_blocked_by_reservations():
    i, _ = setup()
    i.reserve("A-1", 8, "O1", T0 + H)
    i.adjust("A-1", -5, "count")
    assert i.item("A-1").on_hand == 5 and i.available("A-1") == -3
    with pytest.raises(InsufficientStock):
        i.adjust("A-1", -6, "count")                     # 재고 음수는 여전히 안 됨


def test_fulfill_ships_and_removes():
    i, c = setup()
    i.reserve("A-1", 3, "O1", T0 + H)
    c.now = T0 + timedelta(minutes=5)
    i.fulfill("O1")
    assert i.item("A-1").on_hand == 7 and i.available("A-1") == 7
    m = i.history("A-1")[-1]
    assert (m.kind, m.qty, m.note, m.ts) == ("ship", -3, "order O1", T0 + timedelta(minutes=5))
    assert i.reservations() == []
    with pytest.raises(stock.ReservationNotFound):
        i.fulfill("O1")


def test_fulfill_when_everything_reserved():
    i, _ = setup()
    i.reserve("A-1", 10, "O1", T0 + H)
    i.fulfill("O1")
    assert i.item("A-1").on_hand == 0


def test_release():
    i, _ = setup()
    i.reserve("A-1", 3, "O1", T0 + H)
    i.release("O1")
    assert i.available("A-1") == 10
    with pytest.raises(stock.ReservationNotFound):
        i.release("O1")


def test_reservations_sorted_and_filtered():
    i, _ = setup()
    i.receive("B-2", 5)
    i.reserve("A-1", 1, "R2", T0 + 2 * H)
    i.reserve("B-2", 1, "R1", T0 + 2 * H)
    i.reserve("A-1", 1, "R0", T0 + H)
    assert [r.order_id for r in i.reservations()] == ["R0", "R1", "R2"]
    rs = i.reservations("A-1")
    assert [(r.order_id, r.sku, r.qty, r.expires_at) for r in rs] == [("R0", "A-1", 1, T0 + H), ("R2", "A-1", 1, T0 + 2 * H)]
    with pytest.raises(UnknownItem):
        i.available("NOPE")


def test_storage_reads_v1_writes_v2(tmp_path):
    p = tmp_path / "old.json"
    p.write_text(json.dumps({
        "version": 1,
        "items": [{"sku": "A-1", "name": "Apple", "on_hand": 5, "unit_cost": "0.50"}],
        "movements": [{"ts": "2026-01-01T09:00:00", "sku": "A-1", "kind": "receive", "qty": 5, "note": ""}],
    }), encoding="utf-8")
    c = Clock()
    inv = storage.load(p, clock=c)
    assert inv.available("A-1") == 5 and inv.reservations() == []
    inv.reserve("A-1", 2, "O9", T0 + H)
    storage.save(inv, p)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["version"] == 2
    assert data["reservations"] == [{"order_id": "O9", "sku": "A-1", "qty": 2, "expires_at": (T0 + H).isoformat()}]
    back = storage.load(p, clock=c)
    assert back.available("A-1") == 3 and back.reservations()[0].expires_at == T0 + H


@pytest.mark.parametrize("version", [3, 0, None])
def test_storage_rejects_other_versions(tmp_path, version):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"version": version, "items": [], "movements": [], "reservations": []}), encoding="utf-8")
    with pytest.raises(StorageError):
        storage.load(p)


def cli(tmp_path, *args):
    return subprocess.run([sys.executable, "-m", "stock", "--db", str(tmp_path / "s.json"), *args],
                          capture_output=True, text=True, timeout=30)


def test_cli_reservations(tmp_path):
    assert cli(tmp_path, "add", "A-1", "Apple").returncode == 0
    assert cli(tmp_path, "add", "B-2", "Banana").returncode == 0
    assert cli(tmp_path, "receive", "A-1", "10").returncode == 0
    assert cli(tmp_path, "reserve", "A-1", "4", "O1", "--expires", "2099-01-01T00:00:00").returncode == 0
    assert cli(tmp_path, "list").stdout.splitlines() == ["A-1\tApple\t10\t6", "B-2\tBanana\t0\t0"]
    assert cli(tmp_path, "low", "0").stdout.splitlines() == ["B-2\tBanana\t0\t0"]
    assert cli(tmp_path, "reservations").stdout.splitlines() == ["O1\tA-1\t4\t2099-01-01T00:00:00"]
    assert cli(tmp_path, "reservations", "B-2").stdout.strip() == ""
    r = cli(tmp_path, "ship", "A-1", "7")
    assert r.returncode == 1 and r.stderr.startswith("오류:")
    assert cli(tmp_path, "fulfill", "O1").returncode == 0
    assert cli(tmp_path, "list").stdout.splitlines()[0] == "A-1\tApple\t6\t6"
    for args in (["release", "O1"], ["fulfill", "NOPE"],
                 ["reserve", "A-1", "1", "O2", "--expires", "2000-01-01T00:00:00"],
                 ["reserve", "A-1", "99", "O3", "--expires", "2099-01-01T00:00:00"]):
        r = cli(tmp_path, *args)
        assert r.returncode == 1 and r.stderr.startswith("오류:"), args
    assert cli(tmp_path, "reserve", "A-1", "2", "O4", "--expires", "2099-06-01T12:30:00").returncode == 0
    assert cli(tmp_path, "release", "O4").returncode == 0
    assert json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))["version"] == 2
