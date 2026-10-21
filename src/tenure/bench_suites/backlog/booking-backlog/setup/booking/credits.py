"""크레딧 계산과 원장(ledger).

- 예약 비용 = 시간당 크레딧 × 분 / 60, **올림**(정수 크레딧). 예: 시간당 3, 45분 → 2.25 → 3.
- 비수기(off-peak) 할인: 예약 **시작 시각**이 주말(토·일)이거나 평일 18:00 이후 또는 07:00 이전이면
  절반 값(할인한 뒤 올림). 할인 여부는 시작 시각으로만 정한다 — 17:30~19:00 예약은 정가다.
  예: 시간당 4, 90분, 토요일 → 4 × 90 / 60 / 2 = 3.
- 크레딧은 **예약 시작 시각이 속한 달**의 잔액에서 쓴다. 다음 달 예약을 미리 하면 다음 달 크레딧을 쓴다.
  취소 환불도 같은 달(예약 시작이 속한 달)로 돌아간다.
- 잔액(그 달) = 플랜의 월 크레딧 - 그 달 청구 합 + 그 달 환불 합.
- 원장은 청구(charge)와 환불(refund)만 기록한다. 0 크레딧은 기록하지 않는다.
"""

from __future__ import annotations

from datetime import datetime, time

from booking.models import LedgerEntry, Plan, Resource
from booking.timeutil import minutes_between

CHARGE = "charge"
REFUND = "refund"


PEAK_START = time(7, 0)
PEAK_END = time(18, 0)


def is_off_peak(start: datetime) -> bool:
    """시작 시각이 주말이거나 평일 07:00 이전·18:00 이후면 True."""
    return start.weekday() >= 5 or start.time() < PEAK_START or start.time() >= PEAK_END


def cost(resource: Resource, start: datetime, end: datetime) -> int:
    """예약 비용(크레딧, 올림). 비수기는 절반."""
    mins = minutes_between(start, end)
    per = 120 if is_off_peak(start) else 60
    return -(-resource.credits_per_hour * mins // per)


def can_spend(plan: Plan, balance: int, amount: int) -> bool:
    """플랜이 초과 사용을 허용하거나 잔액이 충분하면 True."""
    return plan.overage_price is not None or balance >= amount


class Ledger:
    def __init__(self, entries: list[LedgerEntry] | None = None):
        self.entries: list[LedgerEntry] = list(entries or [])

    def _add(self, kind, member_id, month, credits, booking_id, ts, note):
        if credits <= 0:
            return None
        e = LedgerEntry(ts=ts, member_id=member_id, month=month, kind=kind, credits=credits,
                        booking_id=booking_id, note=note)
        self.entries.append(e)
        return e

    def charge(self, member_id: str, month: str, credits: int, booking_id: int | None, ts: datetime, note: str = ""):
        return self._add(CHARGE, member_id, month, credits, booking_id, ts, note)

    def refund(self, member_id: str, month: str, credits: int, booking_id: int | None, ts: datetime, note: str = ""):
        return self._add(REFUND, member_id, month, credits, booking_id, ts, note)

    def used(self, member_id: str, month: str) -> int:
        """그 달 순사용량 = 청구 - 환불."""
        total = 0
        for e in self.entries:
            if e.member_id != member_id or e.month != month:
                continue
            total += e.credits if e.kind == CHARGE else -e.credits
        return total

    def for_member(self, member_id: str | None = None) -> list[LedgerEntry]:
        return [e for e in self.entries if member_id is None or e.member_id == member_id]
