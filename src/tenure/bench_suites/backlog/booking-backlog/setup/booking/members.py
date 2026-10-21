"""회원과 요금제(플랜).

플랜은 고정된 세 가지다.

| 플랜 | 월 크레딧 | 초과 사용 |
|---|---|---|
| basic | 40 | 불가 (모자라면 InsufficientCredits) |
| pro | 120 | 크레딧당 2.00 |
| payg | 0 | 크레딧당 3.00 |

월 크레딧은 달마다 새로 주어지고 남아도 다음 달로 넘어가지 않는다.
"""

from __future__ import annotations

from decimal import Decimal

from booking.models import Member, Plan, check_id, check_name

PLANS: dict[str, Plan] = {
    "basic": Plan("basic", 40, None),
    "pro": Plan("pro", 120, Decimal("2.00")),
    "payg": Plan("payg", 0, Decimal("3.00")),
}


def get_plan(name: str) -> Plan:
    try:
        return PLANS[name]
    except (KeyError, TypeError):
        raise ValueError(f"없는 플랜: {name!r} (가능: {', '.join(PLANS)})") from None


def new_member(id, name, plan="basic") -> Member:
    check_id(id, "회원")
    name = check_name(name, "회원")
    get_plan(plan)
    return Member(id=id, name=name, plan=plan)
