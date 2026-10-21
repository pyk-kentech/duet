"""취소 수수료 규칙.

알림 시간(notice) = 예약 시작 - 취소 시각.

| 알림 시간 | 수수료 |
|---|---|
| 24시간 이상 | 0% |
| 2시간 이상 24시간 미만 | 50% |
| 2시간 미만 | 100% |

수수료는 그 예약에 청구한 **크레딧** 기준으로 계산하고 **정수 크레딧으로 올림**한다
(예: 3 크레딧의 50% = 1.5 → 2). 환불 = 청구 크레딧 - 수수료.
이미 시작한 예약은 취소할 수 없다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from booking.models import Booking, Cancellation

FREE_NOTICE = timedelta(hours=24)
LATE_NOTICE = timedelta(hours=2)


def fee_percent(notice: timedelta) -> int:
    if notice >= FREE_NOTICE:
        return 0
    if notice >= LATE_NOTICE:
        return 50
    return 100


def fee_credits(charged: int, percent: int) -> int:
    """수수료 크레딧(올림)."""
    return -(-charged * percent // 100)


def settle(booking: Booking, now: datetime) -> Cancellation:
    """수수료와 환불을 계산한다(상태는 바꾸지 않는다)."""
    pct = fee_percent(booking.start - now)
    fee = fee_credits(booking.charged, pct)
    return Cancellation(booking_id=booking.id, fee=fee, refund=booking.charged - fee)
