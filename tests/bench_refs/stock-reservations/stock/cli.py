"""stock CLI: python -m stock [--db 파일] <명령> ..."""

import argparse
import sys
from datetime import datetime

from stock import storage
from stock.errors import StockError


def build_parser():
    p = argparse.ArgumentParser(prog="stock", description="작은 재고 관리")
    p.add_argument("--db", default="stock.json", help="데이터 파일 (기본: stock.json)")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="품목 추가")
    a.add_argument("sku")
    a.add_argument("name")
    a.add_argument("--cost", default="0", help="단가")

    for name in ("receive", "ship"):
        s = sub.add_parser(name, help="입고" if name == "receive" else "출고")
        s.add_argument("sku")
        s.add_argument("qty", type=int)
        s.add_argument("--note", default="")

    j = sub.add_parser("adjust", help="실사 조정")
    j.add_argument("sku")
    j.add_argument("delta", type=int)
    j.add_argument("--reason", required=True)

    sub.add_parser("list", help="품목 목록")
    sub.add_parser("value", help="재고 금액 합계")
    low = sub.add_parser("low", help="재고가 적은 품목")
    low.add_argument("threshold", type=int)
    h = sub.add_parser("history", help="이동 기록")
    h.add_argument("sku", nargs="?")

    r = sub.add_parser("reserve", help="주문 예약")
    r.add_argument("sku")
    r.add_argument("qty", type=int)
    r.add_argument("order_id")
    r.add_argument("--expires", required=True, type=datetime.fromisoformat, help="만료 시각 (ISO 8601)")
    for name in ("release", "fulfill"):
        x = sub.add_parser(name, help="예약 취소" if name == "release" else "예약 출고")
        x.add_argument("order_id")
    rs = sub.add_parser("reservations", help="유효한 예약 목록")
    rs.add_argument("sku", nargs="?")
    return p


def _items(inv, items):
    for i in items:
        print(f"{i.sku}\t{i.name}\t{i.on_hand}\t{inv.available(i.sku)}")


def run(args):
    inv = storage.load(args.db)
    changed = False
    if args.cmd == "add":
        inv.add_item(args.sku, args.name, args.cost)
        changed = True
    elif args.cmd == "receive":
        inv.receive(args.sku, args.qty, args.note)
        changed = True
    elif args.cmd == "ship":
        inv.ship(args.sku, args.qty, args.note)
        changed = True
    elif args.cmd == "adjust":
        inv.adjust(args.sku, args.delta, args.reason)
        changed = True
    elif args.cmd == "list":
        _items(inv, inv.items())
    elif args.cmd == "value":
        print(f"TOTAL\t{inv.value():.2f}")
    elif args.cmd == "low":
        _items(inv, inv.low_stock(args.threshold))
    elif args.cmd == "history":
        for m in inv.history(args.sku):
            print(f"{m.ts.isoformat(timespec='seconds')}\t{m.sku}\t{m.kind}\t{m.qty}\t{m.note}")
    elif args.cmd == "reserve":
        inv.reserve(args.sku, args.qty, args.order_id, args.expires)
        changed = True
    elif args.cmd == "release":
        inv.release(args.order_id)
        changed = True
    elif args.cmd == "fulfill":
        inv.fulfill(args.order_id)
        changed = True
    elif args.cmd == "reservations":
        for r in inv.reservations(args.sku):
            print(f"{r.order_id}\t{r.sku}\t{r.qty}\t{r.expires_at.isoformat()}")
    if changed:
        storage.save(inv, args.db)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        run(args)
    except (StockError, ValueError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    return 0
