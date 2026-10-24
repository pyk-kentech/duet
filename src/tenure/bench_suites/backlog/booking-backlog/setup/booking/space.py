"""예약 장부 ``Space``.

코워킹 스페이스 하나의 자원·회원·예약·반복 예약·대기열·크레딧 원장을 한곳에서 다룬다.
지금 시각은 생성자의 ``clock``(인자 없이 datetime 을 돌려주는 함수)으로만 얻는다. 테스트는
고정 시계를 넘긴다.

예약 규칙 요약 (자세한 것은 README):

- 시각은 15분 단위로 맞춘다(시작 내림, 끝 올림). 예약은 최대 12시간. 지난 시각은 예약할 수 없다
  (내림한 시작 시각이 지금보다 앞이면 ValueError).
- 예약은 시작하는 날의 영업 구간 안에 있어야 한다(OutsideHours). 끝이 닫는 시각과 같아도 된다.
- 같은 자원의 취소되지 않은 예약과 겹치면 Conflict. 한 예약이 끝나는 시각에 다른 예약이 시작하는 것은
  충돌이 아니다 — 단, 버퍼가 있는 자원에서는 다른 회원의 예약과 버퍼 시간 이상 떨어져야 한다.
  같은 회원의 예약끼리는 버퍼가 필요 없다.
- 플랜별 사전 예약 한도(policy.py)를 넘으면 PolicyError.
- 검사 순서: 자원 → 회원 → 시각 값 → 사전 예약 한도 → 인원 → 영업시간 → 충돌 → 크레딧.
  실패하면 아무것도 바뀌지 않는다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from booking import recurrence
from booking.cancellation import settle
from booking.credits import Ledger, can_spend, cost
from booking.errors import (
    AlreadyExists, BookingError, Conflict, InsufficientCredits, OutsideHours, UnknownBooking, UnknownMember,
    UnknownResource, UnknownSeries,
)
from booking.hours import DEFAULT_HOURS, within
from booking.members import get_plan, new_member
from booking.models import ACTIVE, CANCELLED, Booking, Cancellation, Member, Plan, Resource, Series, WaitlistEntry
from booking.notify import Outbox, cancelled_text
from booking.policy import check_advance
from booking.resources import check_attendees, new_resource
from booking.timeutil import (
    MAX_BOOKING, SLOT, SLOT_MINUTES, fmt_dt, month_key, overlaps, require_datetime, snap,
)
from booking.waitlist import Waitlist


def _default_clock() -> datetime:
    return datetime.now().replace(second=0, microsecond=0)


class Space:
    def __init__(self, clock=None):
        self.clock = clock or _default_clock
        self._resources: dict[str, Resource] = {}
        self._members: dict[str, Member] = {}
        self._bookings: dict[int, Booking] = {}
        self._series: dict[int, Series] = {}
        self._waitlist = Waitlist()
        self._ledger = Ledger()
        self._outbox = Outbox()
        self._next_booking = 1
        self._next_series = 1

    # ================================================================ resources
    def add_resource(self, id, name, kind="room", capacity=1, credits_per_hour=4, buffer_minutes=0,
                     hours=DEFAULT_HOURS) -> Resource:
        res = new_resource(id, name, kind=kind, capacity=capacity, credits_per_hour=credits_per_hour,
                           buffer_minutes=buffer_minutes, hours=hours)
        if res.id in self._resources:
            raise AlreadyExists(f"이미 있는 자원: {res.id}")
        self._resources[res.id] = res
        return res

    def resource(self, resource_id) -> Resource:
        try:
            return self._resources[resource_id]
        except (KeyError, TypeError):
            raise UnknownResource(f"없는 자원: {resource_id}") from None

    def resources(self) -> list[Resource]:
        return [self._resources[k] for k in sorted(self._resources)]

    def update_resource(self, resource_id, name=None, capacity=None, credits_per_hour=None, buffer_minutes=None,
                        hours=None) -> Resource:
        """자원 정보 바꾸기(종류는 못 바꾼다). None 인 값은 그대로 둔다.

        이미 있는 예약은 다시 검사하지 않는다(영업시간을 줄여도 기존 예약은 남는다). 바뀐 값은
        이후의 예약·변경·대기 등록부터 적용된다.
        """
        res = self.resource(resource_id)
        fresh = new_resource(res.id, res.name if name is None else name, kind=res.kind,
                             capacity=res.capacity if capacity is None else capacity,
                             credits_per_hour=res.credits_per_hour if credits_per_hour is None else credits_per_hour,
                             buffer_minutes=res.buffer_minutes if buffer_minutes is None else buffer_minutes,
                             hours=res.hours if hours is None else hours)
        res.name, res.capacity, res.credits_per_hour = fresh.name, fresh.capacity, fresh.credits_per_hour
        res.buffer_minutes, res.hours = fresh.buffer_minutes, fresh.hours
        return res

    # ================================================================ members
    def add_member(self, id, name, plan="basic") -> Member:
        m = new_member(id, name, plan)
        if m.id in self._members:
            raise AlreadyExists(f"이미 있는 회원: {m.id}")
        self._members[m.id] = m
        return m

    def member(self, member_id) -> Member:
        try:
            return self._members[member_id]
        except (KeyError, TypeError):
            raise UnknownMember(f"없는 회원: {member_id}") from None

    def members(self) -> list[Member]:
        return [self._members[k] for k in sorted(self._members)]

    def set_plan(self, member_id, plan) -> Member:
        """플랜 바꾸기. 월 크레딧은 늘 지금 플랜 기준으로 계산한다."""
        m = self.member(member_id)
        get_plan(plan)
        m.plan = plan
        return m

    # ================================================================ credits
    def plan_of(self, member_id) -> Plan:
        return get_plan(self.member(member_id).plan)

    def balance(self, member_id, month) -> int:
        """그 달 잔액 = 월 크레딧 - (청구 - 환불). 초과 사용 플랜은 음수일 수 있다."""
        plan = self.plan_of(member_id)
        return plan.monthly_credits - self._ledger.used(member_id, month_key(month))

    def ledger(self, member_id=None):
        """원장 항목(기록 순서). member_id 를 주면 그 회원 것만."""
        if member_id is not None:
            self.member(member_id)
        return self._ledger.for_member(member_id)

    def notifications(self, member_id=None):
        """알림함 (기록 순서). member_id 를 주면 그 회원 것만."""
        if member_id is not None:
            self.member(member_id)
        return self._outbox.for_member(member_id)

    def _ensure_credits(self, member_id, month: str, amount: int) -> None:
        plan = self.plan_of(member_id)
        bal = self.balance(member_id, month)
        if not can_spend(plan, bal, amount):
            raise InsufficientCredits(f"{member_id}: {month} 잔액 {bal}, 필요 {amount}")

    # ================================================================ booking helpers
    def _prepare_times(self, start, end) -> tuple[datetime, datetime]:
        require_datetime(start, "시작 시각")
        require_datetime(end, "끝 시각")
        if end <= start:
            raise ValueError("끝 시각은 시작 시각보다 뒤여야 합니다")
        start, end = snap(start, end)
        if end - start > MAX_BOOKING:
            raise ValueError("예약은 최대 12시간입니다")
        if start < self.clock():
            raise ValueError(f"지난 시각은 예약할 수 없습니다: {fmt_dt(start)}")
        return start, end

    def _check_conflicts(self, resource: Resource, member_id: str, start: datetime, end: datetime,
                         ignore_id: int | None = None) -> None:
        """겹치는 예약이 있으면 Conflict.

        버퍼가 있는 자원이면 다른 회원의 예약과는 버퍼 시간만큼 더 띄운다. 같은 회원의 예약끼리는
        겹치지만 않으면 된다(이어서 쓰는 경우 청소가 필요 없다).
        """
        buf = resource.buffer
        for b in self._bookings.values():
            if b.resource_id != resource.id or not b.active or b.id == ignore_id:
                continue
            pad = buf if (buf and b.member_id != member_id) else timedelta(0)
            if overlaps(start - pad, end + pad, b.start, b.end):
                raise Conflict(f"{resource.id}: 예약 {b.id} ({fmt_dt(b.start)}~{fmt_dt(b.end)}) 와 겹칩니다")

    def _is_taken(self, resource_id: str, start: datetime, end: datetime) -> bool:
        for b in self._bookings.values():
            if b.resource_id == resource_id and b.active and overlaps(start, end, b.start, b.end):
                return True
        return False

    def _create(self, resource: Resource, member_id: str, start: datetime, end: datetime, attendees: int,
                note: str, price: int, series_id: int | None = None) -> Booking:
        now = self.clock()
        b = Booking(id=self._next_booking, resource_id=resource.id, member_id=member_id, start=start, end=end,
                    attendees=attendees, note=note, series_id=series_id, charged=price, created_at=now)
        self._next_booking += 1
        self._bookings[b.id] = b
        self._ledger.charge(member_id, month_key(start), price, b.id, now, note="booking")
        return b

    def _mark_cancelled(self, b: Booking, fee: int, now: datetime) -> None:
        b.status = CANCELLED
        b.fee = fee
        b.cancelled_at = now

    # ================================================================ bookings
    def book(self, resource_id, member_id, start, end, attendees=1, note="") -> Booking:
        """예약 하나를 만든다. 비용은 그 달 크레딧에서 바로 청구한다."""
        res = self.resource(resource_id)
        member = self.member(member_id)
        start, end = self._prepare_times(start, end)
        check_advance(member.plan, start, self.clock())
        check_attendees(res, attendees)
        # 하루를 넘는 예약은 받지 않는다
        if start.date() != end.date():
            raise OutsideHours("예약은 하루 안에서만 할 수 있습니다")
        if not within(res.hours, start, end):
            raise OutsideHours(f"{res.id}: 영업시간 밖입니다 ({fmt_dt(start)}~{fmt_dt(end)})")
        self._check_conflicts(res, member_id, start, end)
        price = cost(res, start, end)
        self._ensure_credits(member_id, month_key(start), price)
        return self._create(res, member_id, start, end, attendees, str(note or ""), price)

    def booking(self, booking_id) -> Booking:
        try:
            return self._bookings[booking_id]
        except (KeyError, TypeError):
            raise UnknownBooking(f"없는 예약: {booking_id}") from None

    def bookings(self, resource_id=None, member_id=None, start=None, end=None, include_cancelled=False) -> list[Booking]:
        """예약 목록 (시작 시각, id 순). start/end 를 주면 [start, end) 와 겹치는 예약만."""
        if resource_id is not None:
            self.resource(resource_id)
        if member_id is not None:
            self.member(member_id)
        out = []
        for b in self._bookings.values():
            if resource_id is not None and b.resource_id != resource_id:
                continue
            if member_id is not None and b.member_id != member_id:
                continue
            if not include_cancelled and not b.active:
                continue
            if start is not None and b.end <= start:
                continue
            if end is not None and b.start >= end:
                continue
            out.append(b)
        return sorted(out, key=lambda b: (b.start, b.id))

    def cancel(self, booking_id) -> Cancellation:
        """예약 취소. 수수료를 뺀 크레딧을 환불하고, 그 자원의 대기열을 승격한다."""
        b = self.booking(booking_id)
        now = self.clock()
        if not b.active:
            raise BookingError(f"이미 취소된 예약입니다: {b.id}")
        if b.start <= now:
            raise BookingError(f"이미 시작한 예약은 취소할 수 없습니다: {b.id}")
        result = settle(b, now)
        self._mark_cancelled(b, result.fee, now)
        self._ledger.refund(b.member_id, month_key(b.start), result.refund, b.id, now, note="cancel")
        self._outbox.add(now, b.member_id, "cancelled", cancelled_text(b.id, result.fee, result.refund))
        self._waitlist.promote(self, b.resource_id)
        return result

    def move(self, booking_id, start, end) -> Booking:
        """예약 시각 바꾸기.

        같은 예약 번호·생성 시각·반복 예약 소속을 유지한다. 취소가 아니므로 수수료가 없고,
        비게 된 원래 시간은 대기자에게 넘기지 않는다(알려진 제약: 대기열 승격은 취소 때만 일어난다).
        """
        b = self.booking(booking_id)
        if not b.active:
            raise BookingError(f"취소된 예약은 바꿀 수 없습니다: {b.id}")
        now = self.clock()
        if b.start <= now:
            raise BookingError(f"이미 시작한 예약은 바꿀 수 없습니다: {b.id}")
        res = self.resource(b.resource_id)
        start, end = self._prepare_times(start, end)
        check_advance(self.member(b.member_id).plan, start, now)
        if start.date() != end.date():
            raise OutsideHours("예약은 하루 안에서만 할 수 있습니다")
        if not within(res.hours, start, end):
            raise OutsideHours(f"{res.id}: 영업시간 밖입니다 ({fmt_dt(start)}~{fmt_dt(end)})")
        for other in self._bookings.values():
            if other.id == b.id or other.resource_id != res.id or not other.active:
                continue
            if overlaps(start, end, other.start, other.end):
                raise Conflict(f"{res.id}: 예약 {other.id} 와 겹칩니다")
        # TODO(2025-11): 길이가 바뀌면 크레딧 차액을 청구/환불해야 한다
        b.start, b.end = start, end
        return b

    # ================================================================ series
    def book_series(self, resource_id, member_id, start, end, freq="weekly", count=None, until=None,
                    attendees=1, note="", skip_conflicts=False) -> Series:
        """반복 예약. 첫 발생 [start, end) 부터 freq 간격으로 count 번 또는 until(날짜, 포함)까지.

        모든 발생을 먼저 검사하고 하나라도 안 되면 아무것도 만들지 않는다. skip_conflicts=True 면
        영업시간 밖이거나 겹치는 발생만 건너뛰고(그 날짜는 exceptions 에 남는다) 나머지를 만든다.
        크레딧은 발생마다 그 달에서 청구하며, 모자라면 skip_conflicts 와 상관없이 InsufficientCredits.
        """
        res = self.resource(resource_id)
        self.member(member_id)
        first, planned, skipped = recurrence.plan_series(self, res, member_id, start, end, freq, count, until,
                                                         attendees, skip_conflicts)
        if isinstance(until, datetime):
            until = until.date()
        s = Series(id=self._next_series, resource_id=res.id, member_id=member_id, start=first[0],
                   end=first[1], freq=freq, count=count, until=until, exceptions=set(skipped))
        self._next_series += 1
        for os_, oe, price in planned:
            b = self._create(res, member_id, os_, oe, attendees, str(note or ""), price, series_id=s.id)
            s.booking_ids.append(b.id)
        self._series[s.id] = s
        return s

    def series(self, series_id) -> Series:
        try:
            return self._series[series_id]
        except (KeyError, TypeError):
            raise UnknownSeries(f"없는 반복 예약: {series_id}") from None

    def all_series(self) -> list[Series]:
        return [self._series[k] for k in sorted(self._series)]

    def _series_bookings(self, s: Series) -> list[Booking]:
        return sorted((self._bookings[i] for i in s.booking_ids), key=lambda b: (b.start, b.id))

    def skip_occurrence(self, series_id, day) -> Cancellation:
        """반복 예약의 한 날짜만 취소한다(수수료 규칙은 일반 취소와 같다). 그 날짜는 exceptions 에 남는다."""
        s = self.series(series_id)
        if isinstance(day, datetime):
            day = day.date()
        if not isinstance(day, date):
            raise ValueError(f"날짜가 필요합니다: {day!r}")
        targets = [b for b in self._series_bookings(s) if b.active and b.start.date() == day]
        if not targets:
            raise BookingError(f"반복 예약 {s.id}: {day.isoformat()} 에 취소할 예약이 없습니다")
        results = recurrence.cancel_occurrences(self, targets)
        s.exceptions.add(day)
        return results[0]

    def cancel_series(self, series_id, from_date=None) -> list[Cancellation]:
        """반복 예약의 앞으로 남은 발생(시작이 지금보다 뒤)을 모두 취소한다. from_date 를 주면 그 날짜부터."""
        s = self.series(series_id)
        now = self.clock()
        if isinstance(from_date, datetime):
            from_date = from_date.date()
        targets = [b for b in self._series_bookings(s)
                   if b.active and b.start > now and (from_date is None or b.start.date() >= from_date)]
        return recurrence.cancel_occurrences(self, targets)

    # ================================================================ waitlist
    def join_waitlist(self, resource_id, member_id, start, end, attendees=1) -> WaitlistEntry:
        """대기 등록. 지금 예약할 수 있는 시간이면 BookingError(대기 대신 예약하라)."""
        res = self.resource(resource_id)
        member = self.member(member_id)
        start, end = self._prepare_times(start, end)
        check_advance(member.plan, start, self.clock())
        check_attendees(res, attendees)
        if not within(res.hours, start, end):
            raise OutsideHours(f"{res.id}: 영업시간 밖입니다 ({fmt_dt(start)}~{fmt_dt(end)})")
        if not self._is_taken(res.id, start, end):
            raise BookingError("지금 예약할 수 있는 시간입니다. 대기 대신 바로 예약하세요")
        for e in self._waitlist.entries(res.id):
            if e.member_id == member_id and e.start == start and e.end == end:
                raise AlreadyExists(f"이미 대기 중입니다: 대기 {e.id}")
        return self._waitlist.add(res.id, member_id, start, end, attendees, self.clock())

    def leave_waitlist(self, entry_id) -> WaitlistEntry:
        return self._waitlist.remove(entry_id)

    def waitlist(self, resource_id=None) -> list[WaitlistEntry]:
        """대기열 (등록 순서)."""
        if resource_id is not None:
            self.resource(resource_id)
        return self._waitlist.entries(resource_id)

    # ================================================================ queries
    def free_slots(self, resource_id, day, minutes) -> list[datetime]:
        """그 날 영업 구간 안에서 minutes 분짜리 예약을 시작할 수 있는 시각들(15분 간격, 지난 시각 제외)."""
        res = self.resource(resource_id)
        if isinstance(day, datetime):
            day = day.date()
        if not isinstance(day, date):
            raise ValueError(f"날짜가 필요합니다: {day!r}")
        if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
            raise ValueError(f"분은 1 이상의 정수: {minutes!r}")
        length = timedelta(minutes=-(-minutes // SLOT_MINUTES) * SLOT_MINUTES)
        if length > MAX_BOOKING:
            raise ValueError("예약은 최대 12시간입니다")
        rng = res.hours.get(day.weekday())
        if not rng:
            return []
        opens = datetime.combine(day, rng[0])
        closes = datetime.combine(day, rng[1])
        now = self.clock()
        out = []
        t = opens
        while t + length <= closes:
            if t >= now:
                clash = False
                for b in self._bookings.values():
                    if b.resource_id == res.id and b.active and overlaps(t, t + length, b.start, b.end):
                        clash = True
                        break
                if not clash:
                    out.append(t)
            t += SLOT
        return out
