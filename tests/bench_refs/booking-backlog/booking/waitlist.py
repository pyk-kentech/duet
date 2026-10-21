"""대기열.

꽉 찬 시간에 대기 등록을 해 두면, 그 자원의 예약이 **취소될 때** 등록 순서(먼저 온 순)대로
훑어서 예약할 수 있게 된 항목을 예약으로 바꾼다(승격).

- 시작 시각이 이미 지난 항목은 승격 때 지운다.
- 아직 부딪히는 예약이 있으면(단건 예약과 같은 충돌·버퍼 규칙) 그대로 남긴다.
- 크레딧이 모자란 회원(초과 사용이 안 되는 계정)은 건너뛰고 대기열에 남긴다. 다음 항목은 계속 본다.
  팀에 속한 회원은 승격 시점의 팀 계정으로 청구한다.
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
    """항목은 id(등록) 순서로 들고 있고, 자원별 사전도 함께 둔다(큰 대기열에서 자원별 조회가 빠르게)."""

    def __init__(self, entries: list[WaitlistEntry] | None = None, next_id: int = 1):
        self._entries: dict[int, WaitlistEntry] = {}
        self._by_res: dict[str, dict[int, WaitlistEntry]] = {}
        for e in sorted(entries or [], key=lambda e: e.id):
            self._put(e)
        self.next_id = max([next_id, *(e.id + 1 for e in self._entries.values())])

    def _put(self, e: WaitlistEntry) -> None:
        self._entries[e.id] = e
        self._by_res.setdefault(e.resource_id, {})[e.id] = e

    def add(self, resource_id: str, member_id: str, start: datetime, end: datetime, attendees: int,
            now: datetime) -> WaitlistEntry:
        e = WaitlistEntry(id=self.next_id, resource_id=resource_id, member_id=member_id, start=start, end=end,
                          attendees=attendees, created_at=now)
        self.next_id += 1
        self._put(e)
        return e

    def remove(self, entry_id) -> WaitlistEntry:
        try:
            e = self._entries.pop(entry_id)
        except (KeyError, TypeError):
            raise UnknownEntry(f"없는 대기 항목: {entry_id}") from None
        self._by_res[e.resource_id].pop(e.id, None)
        return e

    def entries(self, resource_id: str | None = None) -> list[WaitlistEntry]:
        if resource_id is None:
            return list(self._entries.values())
        return list(self._by_res.get(resource_id, {}).values())

    def promote(self, space, resource_id: str) -> list[Booking]:
        """그 자원의 대기열을 등록 순서로 훑어 예약할 수 있는 항목을 예약으로 바꾼다."""
        now = space.clock()
        res = space.resource(resource_id)
        promoted: list[Booking] = []
        for entry in self.entries(resource_id):
            if entry.start <= now:
                self.remove(entry.id)
                continue
            if space._find_conflict(res, entry.member_id, entry.start, entry.end) is not None:
                continue
            price = cost(res, entry.start, entry.end)
            account = space._account_for(entry.member_id)
            if not space._can_charge(account, month_key(entry.start), price):
                continue        # 크레딧 부족: 건너뛰고 남겨 둔다
            b = space._create(res, entry.member_id, entry.start, entry.end, entry.attendees, "waitlist", price,
                              account=account)
            self.remove(entry.id)
            space._outbox.add(now, entry.member_id, "promoted", promoted_text(entry.id, b))
            promoted.append(b)
        return promoted
