"""운영 작업.

- ``purge_cancelled(space, before)``: 시작 시각이 ``before`` 보다 앞이고 수수료가 없는(0) 취소 예약을
  지운다. 수수료가 있는 취소 예약은 청구서에 나오므로 남긴다. 원장은 건드리지 않으므로 잔액은 그대로다.
  반복 예약의 ``booking_ids`` 에서도 뺀다. 지운 개수를 돌려준다.
- ``expire_waitlist(space)``: 시작 시각이 지금 이전인 대기 항목을 지운다. 지운 개수를 돌려준다.
- ``check_integrity(space)``: 저장 전에 돌리는 자가 점검. 문제 목록(문자열)을 돌려준다(비어 있으면 정상).
  같은 자원의 활성 예약끼리 겹침(버퍼는 보지 않는다), 반복 예약이 없는 예약을 가리킴.
"""

from __future__ import annotations

from datetime import datetime

from booking.timeutil import fmt_dt, overlaps, require_datetime


def purge_cancelled(space, before: datetime) -> int:
    require_datetime(before, "기준 시각")
    doomed = [b.id for b in space._bookings.values() if not b.active and not b.fee and b.start < before]
    for bid in doomed:
        b = space._bookings.pop(bid)
        if b.series_id is not None and b.series_id in space._series:
            s = space._series[b.series_id]
            s.booking_ids = [i for i in s.booking_ids if i != bid]
    return len(doomed)


def expire_waitlist(space) -> int:
    now = space.clock()
    gone = [e.id for e in space._waitlist.entries() if e.start <= now]
    for eid in gone:
        space._waitlist.remove(eid)
    return len(gone)


def check_integrity(space) -> list[str]:
    problems: list[str] = []
    by_resource: dict[str, list] = {}
    for b in space._bookings.values():
        if b.active:
            by_resource.setdefault(b.resource_id, []).append(b)
    for rid, items in sorted(by_resource.items()):
        items.sort(key=lambda b: (b.start, b.id))
        for a, b in zip(items, items[1:]):
            if overlaps(a.start, a.end, b.start, b.end):
                problems.append(f"{rid}: 예약 {a.id} 와 {b.id} 가 겹칩니다 ({fmt_dt(b.start)})")
    for s in space._series.values():
        for bid in s.booking_ids:
            if bid not in space._bookings:
                problems.append(f"반복 예약 {s.id}: 없는 예약 {bid}")
    return problems
