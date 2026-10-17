"""JSON 파일 저장. 쓰기는 임시 파일 → 바꿔치기로 원자적으로. 버전 2 를 쓰고 1·2 를 읽는다."""

import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from stock.errors import StorageError
from stock.inventory import MAIN, Inventory
from stock.models import Item, Movement, Warehouse

VERSION = 2


def _moves(data, known):
    out = []
    for m in data.get("movements", []):
        wh = m.get("warehouse", MAIN)
        if wh not in known:
            raise StorageError(f"없는 창고의 이동 기록: {wh}")
        out.append(Movement(ts=datetime.fromisoformat(m["ts"]), sku=m["sku"], kind=m["kind"], qty=int(m["qty"]),
                            note=m.get("note", ""), warehouse=wh))
    return out


def load(path, clock=None) -> Inventory:
    path = Path(path)
    if not path.exists():
        return Inventory(clock=clock)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise StorageError(f"{path} 를 읽을 수 없습니다: {e}") from e
    version = data.get("version") if isinstance(data, dict) else None
    if version not in (1, 2):
        raise StorageError(f"지원하지 않는 형식 버전: {version!r}")
    try:
        if version == 1:
            items = [Item(sku=i["sku"], name=i["name"], on_hand=int(i["on_hand"]),
                          unit_cost=Decimal(i["unit_cost"])) for i in data.get("items", [])]
            return Inventory(items, _moves(data, {MAIN}), clock=clock)
        whs = [Warehouse(w["code"], w["name"]) for w in data.get("warehouses", []) if w["code"] != MAIN]
        known = {MAIN, *(w.code for w in whs)}
        items, stock = [], {}
        for i in data.get("items", []):
            s = {str(k): int(v) for k, v in (i.get("stock") or {}).items()}
            bad = set(s) - known
            if bad:
                raise StorageError(f"없는 창고의 재고: {', '.join(sorted(bad))}")
            items.append(Item(sku=i["sku"], name=i["name"], unit_cost=Decimal(i["unit_cost"])))
            stock[i["sku"]] = s
        return Inventory(items, _moves(data, known), clock=clock, warehouses=whs, stock=stock)
    except StorageError:
        raise
    except (KeyError, TypeError, ValueError, ArithmeticError) as e:
        raise StorageError(f"{path} 형식 오류: {e}") from e


def save(inv: Inventory, path) -> None:
    path = Path(path)
    table = inv.stock_table()
    data = {
        "version": VERSION,
        "warehouses": [{"code": w.code, "name": w.name} for w in inv.warehouses()],
        "items": [{"sku": i.sku, "name": i.name, "stock": table.get(i.sku, {}), "unit_cost": str(i.unit_cost)}
                  for i in inv.items()],
        "movements": [{"ts": m.ts.isoformat(), "sku": m.sku, "kind": m.kind, "qty": m.qty, "note": m.note,
                       "warehouse": m.warehouse} for m in inv.history()],
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
