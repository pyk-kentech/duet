"""JSON 파일 저장. 쓰기는 임시 파일 → 바꿔치기로 원자적으로."""

import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from stock.errors import StorageError
from stock.inventory import Inventory
from stock.models import Item, Movement, Reservation

VERSION = 2
READABLE = (1, 2)


def load(path, clock=None) -> Inventory:
    path = Path(path)
    if not path.exists():
        return Inventory(clock=clock)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise StorageError(f"{path} 를 읽을 수 없습니다: {e}") from e
    if data.get("version") not in READABLE:
        raise StorageError(f"지원하지 않는 형식 버전: {data.get('version')!r}")
    try:
        items = [Item(sku=i["sku"], name=i["name"], on_hand=int(i["on_hand"]),
                      unit_cost=Decimal(i["unit_cost"])) for i in data.get("items", [])]
        moves = [Movement(ts=datetime.fromisoformat(m["ts"]), sku=m["sku"], kind=m["kind"],
                          qty=int(m["qty"]), note=m.get("note", "")) for m in data.get("movements", [])]
        res = [Reservation(order_id=r["order_id"], sku=r["sku"], qty=int(r["qty"]),
                           expires_at=datetime.fromisoformat(r["expires_at"])) for r in data.get("reservations", [])]
    except (KeyError, TypeError, ValueError, ArithmeticError) as e:
        raise StorageError(f"{path} 형식 오류: {e}") from e
    return Inventory(items, moves, clock=clock, reservations=res)


def save(inv: Inventory, path) -> None:
    path = Path(path)
    data = {
        "version": VERSION,
        "items": [{"sku": i.sku, "name": i.name, "on_hand": i.on_hand, "unit_cost": str(i.unit_cost)}
                  for i in inv.items()],
        "movements": [{"ts": m.ts.isoformat(), "sku": m.sku, "kind": m.kind, "qty": m.qty, "note": m.note}
                      for m in inv.history()],
        "reservations": [{"order_id": r.order_id, "sku": r.sku, "qty": r.qty, "expires_at": r.expires_at.isoformat()}
                         for r in inv.reservations()],
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
