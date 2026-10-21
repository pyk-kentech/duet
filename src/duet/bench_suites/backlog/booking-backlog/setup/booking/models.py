"""데이터 모델 (dataclass). 규칙 검사는 하지 않는다 — 검사는 resources/members/space 에서."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

ACTIVE = "active"
CANCELLED = "cancelled"
KINDS = ("room", "desk")

ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,23}$")


def check_id(value, what: str) -> str:
    """자원·회원 id: 소문자로 시작, 소문자·숫자·'-', 24자 이하."""
    if not isinstance(value, str) or not ID_RE.match(value):
        raise ValueError(f"{what} id 형식 오류: {value!r} (소문자로 시작, 소문자·숫자·-, 24자 이하)")
    return value


def check_name(value, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} 이름이 비어 있습니다")
    return value.strip()


@dataclass
class Resource:
    id: str
    name: str
    kind: str = "room"                 # "room" | "desk"
    capacity: int = 1
    credits_per_hour: int = 4
    buffer_minutes: int = 0            # 다른 회원의 예약과 띄워야 하는 시간(청소 등)
    hours: dict[int, tuple[time, time]] = field(default_factory=dict)

    @property
    def buffer(self) -> timedelta:
        return timedelta(minutes=self.buffer_minutes)


@dataclass(frozen=True)
class Plan:
    name: str
    monthly_credits: int
    overage_price: Decimal | None      # 초과 크레딧 1개당 금액. None 이면 초과 사용 불가


@dataclass
class Member:
    id: str
    name: str
    plan: str = "basic"


@dataclass
class Booking:
    id: int
    resource_id: str
    member_id: str
    start: datetime
    end: datetime
    attendees: int = 1
    note: str = ""
    status: str = ACTIVE
    series_id: int | None = None
    charged: int = 0                   # 이 예약으로 청구한 크레딧
    fee: int | None = None             # 취소 수수료(취소된 예약만)
    created_at: datetime | None = None
    cancelled_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.status == ACTIVE

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class Series:
    id: int
    resource_id: str
    member_id: str
    start: datetime                    # 첫 발생의 시작
    end: datetime                      # 첫 발생의 끝
    freq: str                          # "weekly" | "biweekly"
    count: int | None = None
    until: date | None = None
    exceptions: set[date] = field(default_factory=set)     # 건너뛴(또는 만들지 않은) 날짜
    booking_ids: list[int] = field(default_factory=list)


@dataclass
class WaitlistEntry:
    id: int
    resource_id: str
    member_id: str
    start: datetime
    end: datetime
    attendees: int = 1
    created_at: datetime | None = None


@dataclass
class LedgerEntry:
    ts: datetime
    member_id: str
    month: str                         # 'YYYY-MM' — 예약 시작 시각이 속한 달
    kind: str                          # "charge" | "refund"
    credits: int
    booking_id: int | None = None
    note: str = ""


@dataclass(frozen=True)
class Cancellation:
    booking_id: int
    fee: int
    refund: int
