"""알림함(outbox).

실제로 메일을 보내지는 않고 기록만 한다. 운영 스크립트가 ``booking notifications`` 출력을 읽어 보낸다.

| 종류 | 받는 사람 | 글 |
|---|---|---|
| ``cancelled`` | 취소한 예약의 회원 | ``예약 {id} 취소 · 수수료 {fee} · 환불 {refund}`` |
| ``promoted`` | 승격된 회원 | ``대기 {entry_id} → 예약 {booking_id} ({자원 id} {시작}~{끝})`` |

시각 표기는 ``YYYY-MM-DDTHH:MM``. 반복 예약을 취소하면 발생마다 ``cancelled`` 가 하나씩 생긴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from booking.timeutil import fmt_dt


@dataclass(frozen=True)
class Notification:
    ts: datetime
    member_id: str
    kind: str
    text: str


class Outbox:
    def __init__(self, items: list[Notification] | None = None):
        self.items: list[Notification] = list(items or [])

    def add(self, ts: datetime, member_id: str, kind: str, text: str) -> Notification:
        n = Notification(ts=ts, member_id=member_id, kind=kind, text=text)
        self.items.append(n)
        return n

    def for_member(self, member_id: str | None = None) -> list[Notification]:
        return [n for n in self.items if member_id is None or n.member_id == member_id]


def cancelled_text(booking_id: int, fee: int, refund: int) -> str:
    return f"예약 {booking_id} 취소 · 수수료 {fee} · 환불 {refund}"


def promoted_text(entry_id: int, booking) -> str:
    return f"대기 {entry_id} → 예약 {booking.id} ({booking.resource_id} {fmt_dt(booking.start)}~{fmt_dt(booking.end)})"
