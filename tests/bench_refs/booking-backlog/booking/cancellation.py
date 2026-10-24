"""취소 수수료 규칙.

알림 시간(notice) = 예약 시작 - 취소 시각.

| 알림 시간 | 수수료 |
|---|---|
| 48시간 이상 | 0% |
| 24시간 이상 48시간 미만 | 25% |
| 2시간 이상 24시간 미만 | 50% |
| 2시간 미만 | 100% |

- 유예 시간: 예약을 만든 뒤 15분 이내(지금 - created_at ≤ 15분)에 취소하면 알림 시간과 상관없이 0.
- 수수료는 그 예약에 청구한 **크레딧** 기준으로 계산하고 **정수 크레딧으로 올림**한다
  (예: 3 크레딧의 50% = 1.5 → 2). 환불 = 청구 크레딧 - 수수료.
- 취소로 대기자가 승격되어 취소된 시간과 겹치는 예약이 생기면 수수료는 0 이다(Space 가 판단).
- 이미 시작한 예약은 취소할 수 없다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from booking.models import Booking, Cancellation

FREE_NOTICE = timedelta(hours=48)
QUARTER_NOTICE = timedelta(hours=24)
LATE_NOTICE = timedelta(hours=2)
GRACE = timedelta(minutes=15)


def fee_percent(notice: timedelta) -> int:
    if notice >= FREE_NOTICE:
        return 0
    if notice >= QUARTER_NOTICE:
        return 25
    if notice >= LATE_NOTICE:
        return 50
    return 100


def fee_credits(charged: int, percent: int) -> int:
    """수수료 크레딧(올림)."""
    return -(-charged * percent // 100)


def in_grace(booking: Booking, now: datetime) -> bool:
    return booking.created_at is not None and now - booking.created_at <= GRACE


def settle(booking: Booking, now: datetime) -> Cancellation:
    """수수료와 환불을 계산한다(상태는 바꾸지 않는다). 대기자 승격에 따른 면제는 여기서 보지 않는다."""
    pct = 0 if in_grace(booking, now) else fee_percent(booking.start - now)
    fee = fee_credits(booking.charged, pct)
    return Cancellation(booking_id=booking.id, fee=fee, refund=booking.charged - fee)
