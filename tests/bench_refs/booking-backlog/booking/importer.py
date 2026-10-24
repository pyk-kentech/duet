"""CSV 일괄 예약.

머리줄이 있는 CSV(쉼표 구분, UTF-8)를 받아 줄마다 ``Space.book`` 으로 예약한다::

    resource,member,start,end,attendees,note
    room-a,alice,2026-10-21T09:00,2026-10-21T10:00,4,주간 회의
    desk-1,bob,2026-10-21 13:00,2026-10-21 17:00,,

- ``attendees`` 와 ``note`` 열은 없어도 되고 비어 있어도 된다(기본 1, "").
- **전부 아니면 전무**: 한 줄이라도 실패하면 그때까지 만든 예약을 모두 되돌리고(원장·알림 포함,
  예약 번호도 다시 쓴다) ``ImportError_`` 를 낸다. 메시지에 줄 번호(머리줄 = 1)가 들어간다.
- 앞 줄에서 만든 예약도 뒤 줄의 충돌 검사 대상이다.
"""

from __future__ import annotations

import csv
import io

from booking.errors import BookingError
from booking.timeutil import parse_dt

REQUIRED = ("resource", "member", "start", "end")


class ImportError_(BookingError):
    """CSV 가져오기 실패. ``line`` 은 실패한 줄 번호(머리줄 = 1)."""

    def __init__(self, line: int, message: str):
        super().__init__(f"{line}번째 줄: {message}")
        self.line = line


def _rollback(space, created, ledger_len: int, outbox_len: int, next_id: int) -> None:
    for b in created:
        space._bookings.pop(b.id, None)
    space._reindex()
    space._ledger.truncate(ledger_len)
    del space._outbox.items[outbox_len:]
    space._next_booking = next_id


def import_bookings(space, text: str) -> list:
    """CSV 글을 예약으로. 만든 예약 목록을 돌려준다."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ImportError_(1, "머리줄이 없습니다")
    missing = [c for c in REQUIRED if c not in reader.fieldnames]
    if missing:
        raise ImportError_(1, f"필요한 열이 없습니다: {', '.join(missing)}")
    created = []
    ledger_len = len(space._ledger.entries)
    outbox_len = len(space._outbox.items)
    next_id = space._next_booking
    for row in reader:
        line = reader.line_num
        try:
            attendees = int(row.get("attendees") or 1)
            b = space.book(row["resource"].strip(), row["member"].strip(), parse_dt(row["start"]),
                           parse_dt(row["end"]), attendees=attendees, note=(row.get("note") or "").strip())
        except (BookingError, ValueError, AttributeError) as e:
            _rollback(space, created, ledger_len, outbox_len, next_id)
            raise ImportError_(line, str(e)) from e
        created.append(b)
    return created
