"""시각 도우미.

모든 시각은 시간대 정보가 없는(naive) 현지 시각이다. 예약의 최소 단위(슬롯)는 15분이고,
예약 시각은 슬롯 경계로 맞춘다: 시작은 내림, 끝은 올림(초·마이크로초도 따진다).

    10:05 ~ 10:50  ->  10:00 ~ 11:00
    10:00 ~ 10:00:01 -> 10:00 ~ 10:15
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Iterator

SLOT_MINUTES = 15
SLOT = timedelta(minutes=SLOT_MINUTES)
MAX_BOOKING = timedelta(hours=12)        # 예약 하나의 최대 길이

_DT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_HM_RE = re.compile(r"^(\d{2}):(\d{2})$")


def floor_slot(dt: datetime) -> datetime:
    """슬롯 경계로 내림."""
    return dt.replace(minute=dt.minute - dt.minute % SLOT_MINUTES, second=0, microsecond=0)


def ceil_slot(dt: datetime) -> datetime:
    """슬롯 경계로 올림. 이미 경계면 그대로."""
    f = floor_slot(dt)
    return f if f == dt else f + SLOT


def snap(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """(시작 내림, 끝 올림)."""
    return floor_slot(start), ceil_slot(end)


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """반열린 구간 [a_start, a_end) 와 [b_start, b_end) 가 겹치는지.

    한 예약이 끝나는 시각에 다른 예약이 시작하면 겹치지 않는다.
    """
    return a_start < b_end and b_start < a_end


def overlap_minutes(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> int:
    s = max(a_start, b_start)
    e = min(a_end, b_end)
    if e <= s:
        return 0
    return int((e - s).total_seconds() // 60)


def minutes_between(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds() // 60)


def require_datetime(value, what: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{what} 는 datetime 이어야 합니다: {value!r}")
    if value.tzinfo is not None:
        raise ValueError(f"{what} 에 시간대가 있으면 안 됩니다(현지 시각만): {value!r}")
    return value


def parse_dt(text: str) -> datetime:
    """'YYYY-MM-DDTHH:MM' (또는 공백 구분, 초 선택)."""
    m = _DT_RE.match(str(text).strip())
    if not m:
        raise ValueError(f"시각 형식 오류: {text!r} (예: 2026-10-21T09:00)")
    y, mo, d, h, mi, s = m.groups()
    try:
        return datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0))
    except ValueError as e:
        raise ValueError(f"시각 형식 오류: {text!r} ({e})") from None


def fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


def parse_date(text: str) -> date:
    try:
        return date.fromisoformat(str(text).strip())
    except ValueError:
        raise ValueError(f"날짜 형식 오류: {text!r} (예: 2026-10-21)") from None


def month_key(value) -> str:
    """'YYYY-MM' 문자열, date, datetime 을 'YYYY-MM' 으로."""
    if isinstance(value, (date, datetime)):
        return f"{value.year:04d}-{value.month:02d}"
    m = _MONTH_RE.match(str(value).strip())
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ValueError(f"월 형식 오류: {value!r} (예: 2026-10)")
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"


def month_bounds(month: str) -> tuple[datetime, datetime]:
    """월의 [첫날 00:00, 다음 달 첫날 00:00)."""
    y, m = (int(x) for x in month_key(month).split("-"))
    start = datetime(y, m, 1)
    end = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)
    return start, end


def parse_hm(text: str) -> time:
    """'HH:MM' (00:00 ~ 23:45, 분은 15의 배수)."""
    m = _HM_RE.match(str(text).strip())
    if not m:
        raise ValueError(f"시각 형식 오류: {text!r} (예: 08:30)")
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        raise ValueError(f"시각 범위 오류: {text!r}")
    if mi % SLOT_MINUTES:
        raise ValueError(f"영업시간은 {SLOT_MINUTES}분 단위여야 합니다: {text!r}")
    return time(h, mi)


def fmt_hm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def days(start: date, end: date) -> Iterator[date]:
    """[start, end) 의 날짜들."""
    d = start
    while d < end:
        yield d
        d += timedelta(days=1)
