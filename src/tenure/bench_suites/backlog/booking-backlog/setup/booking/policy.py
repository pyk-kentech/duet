"""예약 정책: 플랜별 사전 예약 한도.

회원은 플랜에 따라 정해진 기간 안의 시간만 미리 예약할 수 있다.

| 플랜 | 미리 예약할 수 있는 기간 |
|---|---|
| basic | 30일 |
| pro | 90일 |
| payg | 14일 |

- 기준: 예약 시작 시각 - 지금 이 한도 **이하**여야 한다. 넘으면 ``PolicyError``.
- 단건 예약, 대기 등록, 예약 변경(새 시작 시각 기준)에 적용한다.
- 반복 예약은 **첫 발생만** 본다. 이후 발생은 한도를 넘어도 된다(정기 회의를 위해 일부러 그렇게 했다).
- 대기자 승격은 등록할 때 이미 확인했으므로 다시 보지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from booking.errors import BookingError

ADVANCE_DAYS = {"basic": 30, "pro": 90, "payg": 14}
DEFAULT_ADVANCE_DAYS = 30


class PolicyError(BookingError):
    """예약 정책 위반(사전 예약 한도)."""


def advance_limit(plan_name: str) -> timedelta:
    return timedelta(days=ADVANCE_DAYS.get(plan_name, DEFAULT_ADVANCE_DAYS))


def check_advance(plan_name: str, start: datetime, now: datetime) -> None:
    limit = advance_limit(plan_name)
    if start - now > limit:
        raise PolicyError(f"{plan_name} 플랜은 {limit.days}일 뒤까지만 미리 예약할 수 있습니다")
