"""대기열.

꽉 찬 시간에 대기 등록을 해 두면, 그 자원의 예약이 **취소될 때** 등록 순서(먼저 온 순)대로
훑어서 예약할 수 있게 된 항목을 예약으로 바꾼다(승격).

- 시작 시각이 이미 지난 항목은 승격 때 지운다.
- 아직 겹치는 예약이 있으면 그대로 남긴다.
- 크레딧이 모자란 회원(초과 사용이 안 되는 플랜)은 건너뛰고 대기열에 남긴다. 다음 항목은 계속 본다.
- 승격된 예약은 승격 시각에 만들어진 예약이다(created_at = 승격 시각, 메모 "waitlist").
"""

from __future__ import annotations

from datetime import datetime

from booking.credits import cost
from booking.errors import UnknownEntry
from booking.models import Booking, WaitlistEntry
from booking.notify import promoted_text
from booking.timeutil import month_key


class Waitlist:
    def __init__(self, entries: list[WaitlistEntry] | None = None, next_id: int = 1):
        self._entries: dict[int, WaitlistEntry] = {e.id: e for e in (entries or [])}
        self.next_id = max([next_id, *(e.id + 1 for e in self._entries.values())])

    def add(self, resource_id: str, member_id: str, start: datetime, end: datetime, attendees: int,
            now: datetime) -> WaitlistEntry:
        e = WaitlistEntry(id=self.next_id, resource_id=resource_id, member_id=member_id, start=start, end=end,
                          attendees=attendees, created_at=now)
        self.next_id += 1
        self._entries[e.id] = e
        return e

    def remove(self, entry_id) -> WaitlistEntry:
        try:
            return self._entries.pop(entry_id)
        except (KeyError, TypeError):
            raise UnknownEntry(f"없는 대기 항목: {entry_id}") from None

    def entries(self, resource_id: str | None = None) -> list[WaitlistEntry]:
        return [self._entries[k] for k in sorted(self._entries)
                if resource_id is None or self._entries[k].resource_id == resource_id]

    def promote(self, space, resource_id: str) -> list[Booking]:
        """그 자원의 대기열을 등록 순서로 훑어 예약할 수 있는 항목을 예약으로 바꾼다."""
        now = space.clock()
        res = space.resource(resource_id)
        promoted: list[Booking] = []
        for entry in self.entries(resource_id):
            if entry.start <= now:
                del self._entries[entry.id]
                continue
            taken = False
            for b in space._bookings.values():
                if b.resource_id == resource_id and b.active and b.start < entry.end and entry.start < b.end:
                    taken = True
                    break
            if taken:
                continue
            price = cost(res, entry.start, entry.end)
            month = month_key(entry.start)
            plan = space.plan_of(entry.member_id)
            if plan.overage_price is None and space.balance(entry.member_id, month) < price:
                continue        # 크레딧 부족: 건너뛰고 남겨 둔다
            b = space._create(res, entry.member_id, entry.start, entry.end, entry.attendees, "waitlist", price)
            del self._entries[entry.id]
            space._outbox.add(now, entry.member_id, "promoted", promoted_text(entry.id, b))
            promoted.append(b)
        return promoted
