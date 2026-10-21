"""월 청구서.

``invoice(space, member_id, month)`` 는 그 회원의 그 달(예약 시작 기준) 예약으로 청구서를 만든다.

- 줄: 취소되지 않은 예약은 ``"{자원 이름} HH:MM-HH:MM"`` 과 청구 크레딧,
  수수료가 있는 취소 예약은 ``"취소 수수료 {자원 이름} HH:MM-HH:MM"`` 과 수수료.
  수수료가 0 인 취소 예약은 줄이 없다. 줄은 예약 시작 시각, id 순.
- 사용(used) = 줄 크레딧 합. 초과(overage) = max(0, 사용 - 월 크레딧).
- 금액 = 초과 × 플랜의 크레딧당 금액(소수 둘째 자리). 초과 사용이 없는 플랜은 0.00.

``render_invoice(inv)`` 의 텍스트 형식::

    청구서 2026-10 · alice (basic)
    2026-10-21<TAB>Room A 09:00-10:30<TAB>6
    2026-10-23<TAB>취소 수수료 Room A 14:00-15:00<TAB>2
    사용 8 / 할당 40
    초과 0 크레딧 · 금액 0.00
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from booking.members import get_plan
from booking.timeutil import month_key

CENT = Decimal("0.01")


@dataclass(frozen=True)
class InvoiceLine:
    day: date
    text: str
    credits: int
    booking_id: int


@dataclass
class Invoice:
    owner: str
    month: str
    plan: str
    allowance: int
    lines: list[InvoiceLine] = field(default_factory=list)
    used: int = 0
    overage: int = 0
    amount: Decimal = Decimal("0.00")


def _span(space, b) -> str:
    res = space.resource(b.resource_id)
    return f"{res.name} {b.start:%H:%M}-{b.end:%H:%M}"


def invoice(space, member_id: str, month) -> Invoice:
    member = space.member(member_id)
    plan = get_plan(member.plan)
    m = month_key(month)
    lines: list[InvoiceLine] = []
    for b in space.bookings(member_id=member_id, include_cancelled=True):
        if month_key(b.start) != m:
            continue
        if b.active:
            lines.append(InvoiceLine(b.start.date(), _span(space, b), b.charged, b.id))
        elif b.fee:
            lines.append(InvoiceLine(b.start.date(), f"취소 수수료 {_span(space, b)}", b.fee, b.id))
    used = sum(line.credits for line in lines)
    overage = max(0, used - plan.monthly_credits)
    if plan.overage_price is None:
        amount = Decimal("0.00")
    else:
        amount = (plan.overage_price * overage).quantize(CENT)
    return Invoice(owner=member.id, month=m, plan=plan.name, allowance=plan.monthly_credits, lines=lines,
                   used=used, overage=overage, amount=amount)


def render_invoice(inv: Invoice) -> str:
    out = [f"청구서 {inv.month} · {inv.owner} ({inv.plan})"]
    for line in inv.lines:
        out.append(f"{line.day.isoformat()}\t{line.text}\t{line.credits}")
    out.append(f"사용 {inv.used} / 할당 {inv.allowance}")
    out.append(f"초과 {inv.overage} 크레딧 · 금액 {inv.amount:.2f}")
    return "\n".join(out) + "\n"
