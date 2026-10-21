"""보고서: 가동률(utilization)과 크레딧 사용량.

가동률 ``utilization(space, start, end, resource_id=None)``
    - 기간 [start, end) 동안 자원마다 영업 시간(분)과 예약된 시간(분)을 센다.
    - 영업 시간 = 영업 구간 중 기간 안에 들어가는 부분의 합(실제 시각 기준이라 자정을 넘는 구간은
      다음 날짜에 걸친 부분도 그 시각대로 센다).
    - 예약된 시간 = 취소되지 않은 예약 중 기간 안에 들어가는 부분의 합.
    - percent = 예약 / 영업 × 100 을 소수 첫째 자리로 반올림(파이썬 round). 영업 시간이 0 이면 0.0.
    - 자원 id 순. 예약을 한 번만 훑는다(큰 데이터에서도 빠르게).

크레딧 사용량 ``credit_usage(space, month)``
    - 회원 id 순으로 (회원, 플랜, 월 크레딧, 사용, 잔액). 회원 **개인 계정**만 센다.

팀 크레딧 사용량 ``team_usage(space, month)``
    - 팀 id 순으로 (팀, 월 크레딧, 사용, 잔액).

하루 일정 ``agenda(space, day, resource_id=None)``
    - 그 날 [00:00, 다음 날 00:00) 과 겹치는 취소되지 않은 예약을 자원 id, 시작 시각, 예약 id 순으로.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from booking.hours import open_interval
from booking.members import get_plan
from booking.timeutil import month_key, overlap_minutes, require_datetime


@dataclass(frozen=True)
class UtilizationRow:
    resource_id: str
    open_minutes: int
    booked_minutes: int
    percent: float


@dataclass(frozen=True)
class AgendaRow:
    resource_id: str
    start: datetime
    end: datetime
    member_id: str
    note: str
    booking_id: int


@dataclass(frozen=True)
class UsageRow:
    member_id: str
    plan: str
    allowance: int
    used: int
    balance: int


@dataclass(frozen=True)
class TeamUsageRow:
    team_id: str
    allowance: int
    used: int
    balance: int


def utilization(space, start: datetime, end: datetime, resource_id: str | None = None) -> list[UtilizationRow]:
    require_datetime(start, "시작 시각")
    require_datetime(end, "끝 시각")
    if end <= start:
        raise ValueError("끝 시각은 시작 시각보다 뒤여야 합니다")
    targets = [space.resource(resource_id)] if resource_id is not None else space.resources()
    booked = {res.id: 0 for res in targets}
    for b in space.bookings(resource_id=resource_id, start=start, end=end):
        if b.resource_id in booked:
            booked[b.resource_id] += overlap_minutes(b.start, b.end, start, end)
    rows = []
    for res in targets:
        open_total = 0
        d = start.date() - timedelta(days=1)          # 전날의 자정을 넘는 구간
        last = end.date()
        while d <= last:
            iv = open_interval(res.hours, d)
            if iv is not None:
                open_total += overlap_minutes(iv[0], iv[1], start, end)
            d += timedelta(days=1)
        used = booked[res.id]
        pct = round(used * 100 / open_total, 1) if open_total else 0.0
        rows.append(UtilizationRow(res.id, open_total, used, pct))
    return rows


def credit_usage(space, month) -> list[UsageRow]:
    m = month_key(month)
    rows = []
    for member in space.members():
        plan = get_plan(member.plan)
        bal = space.balance(member.id, m)
        rows.append(UsageRow(member.id, plan.name, plan.monthly_credits, plan.monthly_credits - bal, bal))
    return rows


def team_usage(space, month) -> list[TeamUsageRow]:
    m = month_key(month)
    rows = []
    for team in space.teams():
        bal = space.team_balance(team.id, m)
        rows.append(TeamUsageRow(team.id, team.monthly_credits, team.monthly_credits - bal, bal))
    return rows


def agenda(space, day, resource_id: str | None = None) -> list[AgendaRow]:
    if isinstance(day, datetime):
        day = day.date()
    lo = datetime.combine(day, time())
    hi = lo + timedelta(days=1)
    rows = [AgendaRow(b.resource_id, b.start, b.end, b.member_id, b.note, b.id)
            for b in space.bookings(resource_id=resource_id, start=lo, end=hi)]
    rows.sort(key=lambda r: (r.resource_id, r.start, r.booking_id))
    return rows
