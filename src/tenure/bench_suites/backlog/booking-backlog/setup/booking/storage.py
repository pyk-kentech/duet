"""JSON 파일 저장.

- 쓰기는 같은 폴더의 임시 파일에 쓴 뒤 ``os.replace`` 로 바꿔치기한다(원자적).
- 파일이 없으면 빈 Space.
- 최상위 ``version`` 으로 형식을 구분한다. 지금 쓰는 형식은 2, 읽을 수 있는 형식은 1·2.
  그 밖의 버전, JSON 이 아닌 파일, 필드가 빠졌거나 잘못된 파일은 ``StorageError``.

형식 2::

    {
      "version": 2,
      "next_ids": {"booking": 13, "series": 3},
      "resources": [{"id", "name", "kind", "capacity", "credits_per_hour", "buffer_minutes", "hours"}],
      "members":   [{"id", "name", "plan"}],
      "bookings":  [{"id", "resource", "member", "start", "end", "attendees", "note", "status",
                     "series", "charged", "fee", "created_at", "cancelled_at"}],
      "series":    [{"id", "resource", "member", "start", "end", "freq", "count", "until",
                     "exceptions", "bookings"}],
      "ledger":    [{"ts", "member", "month", "kind", "credits", "booking", "note"}],
      "notifications": [{"ts", "member", "kind", "text"}]
    }

시각은 ISO 8601 문자열(``datetime.isoformat()``), 날짜는 ``YYYY-MM-DD``, 영업시간은
``format_hours`` 의 표준 문자열이다.

형식 1(예전 판, 읽기만)::

    {"version": 1,
     "rooms":    [{"id", "name", "capacity", "credits_per_hour", "open": "08:00", "close": "20:00"}],
     "members":  [{"id", "name", "plan"}],
     "bookings": [{"id", "room", "member", "start", "minutes", "credits", "cancelled"}]}

형식 1 은 회의실만 있었고 월~금 영업, 버퍼 없음이다. 예약의 생성 시각이 없어서
``LEGACY_CREATED_AT``(2000-01-01 00:00)으로 읽는다. 취소되지 않은 예약은 원장에 청구 기록을
만들어 넣고(시각 = LEGACY_CREATED_AT), 취소된 예약은 수수료 0·원장 기록 없음으로 읽는다.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from booking.errors import BookingError, StorageError
from booking.hours import format_hours
from booking.models import ACTIVE, CANCELLED, Booking, LedgerEntry, Series
from booking.notify import Notification
from booking.space import Space
from booking.timeutil import month_key

VERSION = 2
READABLE = (1, 2)
LEGACY_CREATED_AT = datetime(2000, 1, 1)


def _dt(value):
    return None if value is None else datetime.fromisoformat(value)


def _iso(value):
    return None if value is None else value.isoformat()


def _opt_int(value):
    return None if value is None else int(value)


def load(path, clock=None) -> Space:
    path = Path(path)
    if not path.exists():
        return Space(clock=clock)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise StorageError(f"{path} 를 읽을 수 없습니다: {e}") from e
    if not isinstance(data, dict):
        raise StorageError(f"{path} 형식 오류: 최상위가 객체가 아닙니다")
    version = data.get("version")
    if version not in READABLE or isinstance(version, bool):
        raise StorageError(f"지원하지 않는 형식 버전: {version!r}")
    try:
        if version == 1:
            return _load_v1(data, clock)
        return _load_v2(data, clock)
    except StorageError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, ArithmeticError, BookingError) as e:
        raise StorageError(f"{path} 형식 오류: {e}") from e


def _check_refs(space: Space, resource_id, member_id) -> None:
    space.resource(resource_id)
    space.member(member_id)


def _load_v1(data, clock) -> Space:
    space = Space(clock=clock)
    for r in data.get("rooms", []):
        space.add_resource(r["id"], r["name"], kind="room", capacity=int(r.get("capacity", 1)),
                           credits_per_hour=int(r.get("credits_per_hour", 4)), buffer_minutes=0,
                           hours=f"mon-fri {r.get('open', '08:00')}-{r.get('close', '20:00')}")
    for m in data.get("members", []):
        space.add_member(m["id"], m["name"], m.get("plan", "basic"))
    bookings = {}
    ledger = []
    for raw in data.get("bookings", []):
        _check_refs(space, raw["room"], raw["member"])
        start = datetime.fromisoformat(raw["start"])
        cancelled = bool(raw.get("cancelled", False))
        b = Booking(id=int(raw["id"]), resource_id=raw["room"], member_id=raw["member"], start=start,
                    end=start + timedelta(minutes=int(raw["minutes"])), charged=int(raw.get("credits", 0)),
                    status=CANCELLED if cancelled else ACTIVE, fee=0 if cancelled else None,
                    created_at=LEGACY_CREATED_AT)
        bookings[b.id] = b
        if not cancelled and b.charged > 0:
            ledger.append(LedgerEntry(ts=LEGACY_CREATED_AT, member_id=b.member_id, month=month_key(b.start),
                                      kind="charge", credits=b.charged, booking_id=b.id, note="v1"))
    space._bookings = bookings
    space._ledger.entries = ledger
    space._next_booking = max(bookings, default=0) + 1
    return space


def _load_v2(data, clock) -> Space:
    space = Space(clock=clock)
    for r in data.get("resources", []):
        space.add_resource(r["id"], r["name"], kind=r.get("kind", "room"), capacity=int(r.get("capacity", 1)),
                           credits_per_hour=int(r.get("credits_per_hour", 4)),
                           buffer_minutes=int(r.get("buffer_minutes", 0)), hours=r.get("hours", ""))
    for m in data.get("members", []):
        space.add_member(m["id"], m["name"], m.get("plan", "basic"))
    bookings = {}
    for raw in data.get("bookings", []):
        _check_refs(space, raw["resource"], raw["member"])
        status = raw.get("status", ACTIVE)
        if status not in (ACTIVE, CANCELLED):
            raise StorageError(f"예약 상태 오류: {status!r}")
        b = Booking(id=int(raw["id"]), resource_id=raw["resource"], member_id=raw["member"],
                    start=datetime.fromisoformat(raw["start"]), end=datetime.fromisoformat(raw["end"]),
                    attendees=int(raw.get("attendees", 1)), note=raw.get("note", ""), status=status,
                    series_id=_opt_int(raw.get("series")), charged=int(raw.get("charged", 0)),
                    fee=_opt_int(raw.get("fee")),
                    created_at=_dt(raw.get("created_at")), cancelled_at=_dt(raw.get("cancelled_at")))
        bookings[b.id] = b
    series = {}
    for raw in data.get("series", []):
        _check_refs(space, raw["resource"], raw["member"])
        s = Series(id=int(raw["id"]), resource_id=raw["resource"], member_id=raw["member"],
                   start=datetime.fromisoformat(raw["start"]), end=datetime.fromisoformat(raw["end"]),
                   freq=raw["freq"], count=_opt_int(raw.get("count")),
                   until=date.fromisoformat(raw["until"]) if raw.get("until") else None,
                   exceptions={date.fromisoformat(d) for d in raw.get("exceptions", [])},
                   booking_ids=[int(i) for i in raw.get("bookings", [])])
        for i in s.booking_ids:
            if i not in bookings:
                raise StorageError(f"반복 예약 {s.id}: 없는 예약 {i}")
        series[s.id] = s
    ledger = []
    for raw in data.get("ledger", []):
        space.member(raw["member"])
        ledger.append(LedgerEntry(ts=datetime.fromisoformat(raw["ts"]), member_id=raw["member"],
                                  month=month_key(raw["month"]), kind=raw["kind"], credits=int(raw["credits"]),
                                  booking_id=raw.get("booking"), note=raw.get("note", "")))
    notes = []
    for raw in data.get("notifications", []):
        space.member(raw["member"])
        notes.append(Notification(ts=datetime.fromisoformat(raw["ts"]), member_id=raw["member"], kind=raw["kind"],
                                  text=raw["text"]))
    ids = data.get("next_ids", {})
    space._outbox.items = notes
    space._bookings = bookings
    space._series = series
    space._ledger.entries = ledger
    space._next_booking = max(int(ids.get("booking", 1)), max(bookings, default=0) + 1)
    space._next_series = max(int(ids.get("series", 1)), max(series, default=0) + 1)
    return space


def to_data(space: Space) -> dict:
    return {
        "version": VERSION,
        "next_ids": {"booking": space._next_booking, "series": space._next_series},
        "resources": [{"id": r.id, "name": r.name, "kind": r.kind, "capacity": r.capacity,
                       "credits_per_hour": r.credits_per_hour, "buffer_minutes": r.buffer_minutes,
                       "hours": format_hours(r.hours)} for r in space.resources()],
        "members": [{"id": m.id, "name": m.name, "plan": m.plan} for m in space.members()],
        "bookings": [{"id": b.id, "resource": b.resource_id, "member": b.member_id, "start": _iso(b.start),
                      "end": _iso(b.end), "attendees": b.attendees, "note": b.note, "status": b.status,
                      "series": b.series_id, "charged": b.charged, "fee": b.fee,
                      "created_at": _iso(b.created_at), "cancelled_at": _iso(b.cancelled_at)}
                     for b in sorted(space._bookings.values(), key=lambda b: b.id)],
        "series": [{"id": s.id, "resource": s.resource_id, "member": s.member_id, "start": _iso(s.start),
                    "end": _iso(s.end), "freq": s.freq, "count": s.count,
                    "until": s.until.isoformat() if s.until else None,
                    "exceptions": sorted(d.isoformat() for d in s.exceptions), "bookings": list(s.booking_ids)}
                   for s in space.all_series()],
        "ledger": [{"ts": _iso(e.ts), "member": e.member_id, "month": e.month, "kind": e.kind,
                    "credits": e.credits, "booking": e.booking_id, "note": e.note} for e in space.ledger()],
        "notifications": [{"ts": _iso(n.ts), "member": n.member_id, "kind": n.kind, "text": n.text}
                          for n in space.notifications()],
    }


def save(space: Space, path) -> None:
    path = Path(path)
    data = to_data(space)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        raise StorageError(f"{path} 에 쓸 수 없습니다: {e}") from e
