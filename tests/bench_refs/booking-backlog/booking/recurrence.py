"""반복 예약(매주·격주).

발생 k(0부터) = 첫 발생 + k × 간격(weekly 7일, biweekly 14일).
``count``(1~104) 또는 ``until``(날짜, 그날 시작하는 발생까지 포함) 중 **정확히 하나**를 준다.

이 모듈은 반복 예약을 만들기 전에 발생마다 영업시간·충돌·크레딧을 검사하고(``plan_series``),
여러 발생을 한꺼번에 취소한다(``cancel_occurrences``). 검사 규칙은 단건 예약과 같은 것을 Space 에서
가져다 쓴다(영업시간 ``Space._check_hours``, 충돌 ``Space._find_conflict``, 비용 ``credits.cost``,
취소 ``Space._cancel_one``). 실제 예약 생성은 Space 가 한다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from booking.credits import cost
from booking.errors import BookingError, Conflict, InsufficientCredits, OutsideHours
from booking.models import Cancellation
from booking.policy import check_advance
from booking.resources import check_attendees
from booking.timeutil import MAX_BOOKING, month_key, require_datetime, snap

FREQS = {"weekly": 7, "biweekly": 14}
MAX_OCCURRENCES = 104


def first_occurrence(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """첫 발생을 15분 단위로 맞춘다 (시작 내림, 끝 올림)."""
    return snap(start, end)


def expand(start: datetime, end: datetime, freq: str, count=None, until=None) -> list[tuple[datetime, datetime]]:
    """발생 목록 [(시작, 끝), ...]. 검사는 하지 않는다."""
    if freq not in FREQS:
        raise ValueError(f"반복 주기는 weekly 또는 biweekly: {freq!r}")
    if (count is None) == (until is None):
        raise ValueError("count 와 until 중 정확히 하나를 주어야 합니다")
    step = timedelta(days=FREQS[freq])
    if count is not None:
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_OCCURRENCES:
            raise ValueError(f"count 는 1~{MAX_OCCURRENCES}: {count!r}")
        n = count
    else:
        if isinstance(until, datetime):
            until = until.date()
        if not isinstance(until, date):
            raise ValueError(f"until 은 날짜여야 합니다: {until!r}")
        if until < start.date():
            raise ValueError("until 이 첫 발생보다 앞입니다")
        n = (until - start.date()).days // step.days + 1
        if n > MAX_OCCURRENCES:
            raise ValueError(f"발생이 너무 많습니다({n}개, 최대 {MAX_OCCURRENCES})")
    return [(start + k * step, end + k * step) for k in range(n)]


def plan_series(space, res, member_id, start, end, freq, count, until, attendees, skip_conflicts):
    """반복 예약을 검사하고 만들 발생을 정한다.

    돌려주는 값: ((첫 발생 시작, 끝), [(시작, 끝, 크레딧), ...], [건너뛴 날짜, ...])
    """
    require_datetime(start, "시작 시각")
    require_datetime(end, "끝 시각")
    if end <= start:
        raise ValueError("끝 시각은 시작 시각보다 뒤여야 합니다")
    start, end = first_occurrence(start, end)
    if end - start > MAX_BOOKING:
        raise ValueError("예약은 최대 12시간입니다")
    if start < space.clock():
        raise ValueError("지난 시각은 예약할 수 없습니다")
    check_advance(space.member(member_id).plan, start, space.clock())     # 첫 발생만 본다
    check_attendees(res, attendees)

    planned: list[tuple[datetime, datetime, int]] = []
    skipped: list[date] = []
    for os_, oe in expand(start, end, freq, count, until):
        try:
            space._check_hours(res, os_, oe)
        except OutsideHours:
            if skip_conflicts:
                skipped.append(os_.date())
                continue
            raise OutsideHours(f"{res.id}: {os_.date().isoformat()} 발생이 영업시간 밖입니다") from None
        clash = space._find_conflict(res, member_id, os_, oe)
        if clash is not None:
            if skip_conflicts:
                skipped.append(os_.date())
                continue
            raise Conflict(f"{res.id}: {os_.date().isoformat()} 발생이 예약 {clash.id} 와 겹칩니다")
        planned.append((os_, oe, cost(res, os_, oe)))
    if not planned:
        raise BookingError("만들 수 있는 발생이 없습니다")

    # 크레딧은 달마다 합쳐서 확인 (초과 사용이 안 되는 계정만)
    account = space._account_for(member_id)
    need: dict[str, int] = {}
    for os_, _oe, price in planned:
        need[month_key(os_)] = need.get(month_key(os_), 0) + price
    for month in sorted(need):
        if not space._can_charge(account, month, need[month]):
            bal = space._account_balance(account, month)
            raise InsufficientCredits(f"{account}: {month} 잔액 {bal}, 필요 {need[month]}")
    return (start, end), planned, skipped


def cancel_occurrences(space, bookings) -> list[Cancellation]:
    """발생 여러 개를 시작 시각 순으로 취소한다. 하나라도 이미 시작했으면 아무것도 취소하지 않는다.

    발생마다 일반 취소와 같은 규칙(수수료 표·유예·대기자 승격과 면제)을 차례로 적용한다.
    """
    now = space.clock()
    bookings = sorted(bookings, key=lambda b: (b.start, b.id))
    for b in bookings:
        if b.start <= now:
            raise BookingError(f"이미 시작한 예약은 취소할 수 없습니다: {b.id}")
    return [space._cancel_one(b, now, "series cancel") for b in bookings]
