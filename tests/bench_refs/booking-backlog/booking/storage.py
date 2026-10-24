"""JSON 파일 저장.

- 쓰기는 같은 폴더의 임시 파일에 쓴 뒤 ``os.replace`` 로 바꿔치기한다(원자적).
- 파일이 없으면 빈 Space.
- 최상위 ``version`` 으로 형식을 구분한다. 지금 쓰는 형식은 3, 읽을 수 있는 형식은 1·2·3.
  그 밖의 버전(정수 1·2·3 이 아닌 모든 값), JSON 이 아닌 파일, 필드가 빠졌거나 잘못된 파일은 ``StorageError``.

형식 3::

    {
      "version": 3,
      "next_ids": {"booking": 13, "series": 3, "waitlist": 4},
      "resources": [{"id", "name", "kind", "capacity", "credits_per_hour", "buffer_minutes", "hours"}],
      "members":   [{"id", "name", "plan"}],
      "teams":     [{"id", "name", "monthly_credits", "overage_price", "members": [회원 id, ...]}],
      "bookings":  [{"id", "resource", "member", "start", "end", "attendees", "note", "status",
                     "series", "charged", "fee", "created_at", "cancelled_at", "account"}],
      "series":    [{"id", "resource", "member", "start", "end", "freq", "count", "until",
                     "exceptions", "bookings"}],
      "waitlist":  [{"id", "resource", "member", "start", "end", "attendees", "created_at"}],
      "ledger":    [{"ts", "member", "month", "kind", "credits", "booking", "note", "account"}],
      "notifications": [{"ts", "member", "kind", "text"}]
    }

시각은 ISO 8601 문자열(``datetime.isoformat()``), 날짜는 ``YYYY-MM-DD``, 영업시간은
``format_hours`` 의 표준 문자열, 팀의 ``overage_price`` 는 금액 문자열 또는 null, 계정은
``member:<회원 id>`` 또는 ``team:<팀 id>``. 대기열은 등록 순서(id 순)이고, 대기 번호는 지운 뒤에도
다시 쓰지 않는다(``next_ids.waitlist``). 없는 회원·팀·자원을 가리키면 ``StorageError``.

형식 2 는 형식 3 에서 ``teams``·``waitlist``·``account``·``next_ids.waitlist`` 가 없는 것이다.
읽으면 대기열·팀 없음, 모든 계정은 ``member:<회원 id>``.

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
from booking.models import (
    ACTIVE, CANCELLED, Booking, LedgerEntry, Series, WaitlistEntry, member_account, team_account,
)
from booking.notify import Notification
from booking.space import Space
from booking.timeutil import month_key
from booking.waitlist import Waitlist

VERSION = 3
READABLE = (1, 2, 3)
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
    if type(version) is not int or version not in READABLE:
        raise StorageError(f"지원하지 않는 형식 버전: {version!r}")
    try:
        if version == 1:
            space = _load_v1(data, clock)
        else:
            space = _load_v23(data, clock, version)
    except StorageError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, ArithmeticError, BookingError) as e:
        raise StorageError(f"{path} 형식 오류: {e}") from e
    space._reindex()
    return space


def _check_refs(space: Space, resource_id, member_id) -> None:
    space.resource(resource_id)
    space.member(member_id)


def _check_account(space: Space, account) -> str:
    if not isinstance(account, str):
        raise StorageError(f"계정 형식 오류: {account!r}")
    kind, _, ident = account.partition(":")
    if kind == "member":
        space.member(ident)
    elif kind == "team":
        space.team(ident)
    else:
        raise StorageError(f"계정 형식 오류: {account!r}")
    return account


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


def _load_v23(data, clock, version: int) -> Space:
    space = Space(clock=clock)
    for r in data.get("resources", []):
        space.add_resource(r["id"], r["name"], kind=r.get("kind", "room"), capacity=int(r.get("capacity", 1)),
                           credits_per_hour=int(r.get("credits_per_hour", 4)),
                           buffer_minutes=int(r.get("buffer_minutes", 0)), hours=r.get("hours", ""))
    for m in data.get("members", []):
        space.add_member(m["id"], m["name"], m.get("plan", "basic"))
    if version >= 3:
        for t in data.get("teams", []):
            space.add_team(t["id"], t["name"], int(t["monthly_credits"]), t.get("overage_price"))
            for mid in t.get("members", []):
                if space.member(mid).team is not None:
                    raise StorageError(f"회원 {mid} 가 팀 두 곳에 있습니다")
                space.join_team(mid, t["id"])
    bookings = {}
    for raw in data.get("bookings", []):
        _check_refs(space, raw["resource"], raw["member"])
        status = raw.get("status", ACTIVE)
        if status not in (ACTIVE, CANCELLED):
            raise StorageError(f"예약 상태 오류: {status!r}")
        account = member_account(raw["member"])
        if version >= 3 and raw.get("account") is not None:
            account = _check_account(space, raw["account"])
        b = Booking(id=int(raw["id"]), resource_id=raw["resource"], member_id=raw["member"],
                    start=datetime.fromisoformat(raw["start"]), end=datetime.fromisoformat(raw["end"]),
                    attendees=int(raw.get("attendees", 1)), note=raw.get("note", ""), status=status,
                    series_id=_opt_int(raw.get("series")), charged=int(raw.get("charged", 0)),
                    fee=_opt_int(raw.get("fee")),
                    created_at=_dt(raw.get("created_at")), cancelled_at=_dt(raw.get("cancelled_at")),
                    account=account)
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
        account = member_account(raw["member"])
        if version >= 3 and raw.get("account") is not None:
            account = _check_account(space, raw["account"])
        ledger.append(LedgerEntry(ts=datetime.fromisoformat(raw["ts"]), member_id=raw["member"],
                                  month=month_key(raw["month"]), kind=raw["kind"], credits=int(raw["credits"]),
                                  booking_id=raw.get("booking"), note=raw.get("note", ""), account=account))
    notes = []
    for raw in data.get("notifications", []):
        space.member(raw["member"])
        notes.append(Notification(ts=datetime.fromisoformat(raw["ts"]), member_id=raw["member"], kind=raw["kind"],
                                  text=raw["text"]))
    ids = data.get("next_ids", {})
    entries = []
    if version >= 3:
        for raw in data.get("waitlist", []):
            _check_refs(space, raw["resource"], raw["member"])
            entries.append(WaitlistEntry(id=int(raw["id"]), resource_id=raw["resource"], member_id=raw["member"],
                                         start=datetime.fromisoformat(raw["start"]),
                                         end=datetime.fromisoformat(raw["end"]),
                                         attendees=int(raw.get("attendees", 1)), created_at=_dt(raw.get("created_at"))))
    space._waitlist = Waitlist(entries, next_id=int(ids.get("waitlist", 1)))
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
        "next_ids": {"booking": space._next_booking, "series": space._next_series,
                     "waitlist": space._waitlist.next_id},
        "resources": [{"id": r.id, "name": r.name, "kind": r.kind, "capacity": r.capacity,
                       "credits_per_hour": r.credits_per_hour, "buffer_minutes": r.buffer_minutes,
                       "hours": format_hours(r.hours)} for r in space.resources()],
        "members": [{"id": m.id, "name": m.name, "plan": m.plan} for m in space.members()],
        "teams": [{"id": t.id, "name": t.name, "monthly_credits": t.monthly_credits,
                   "overage_price": None if t.overage_price is None else str(t.overage_price),
                   "members": list(t.members)} for t in space.teams()],
        "bookings": [{"id": b.id, "resource": b.resource_id, "member": b.member_id, "start": _iso(b.start),
                      "end": _iso(b.end), "attendees": b.attendees, "note": b.note, "status": b.status,
                      "series": b.series_id, "charged": b.charged, "fee": b.fee,
                      "created_at": _iso(b.created_at), "cancelled_at": _iso(b.cancelled_at),
                      "account": b.account}
                     for b in sorted(space._bookings.values(), key=lambda b: b.id)],
        "series": [{"id": s.id, "resource": s.resource_id, "member": s.member_id, "start": _iso(s.start),
                    "end": _iso(s.end), "freq": s.freq, "count": s.count,
                    "until": s.until.isoformat() if s.until else None,
                    "exceptions": sorted(d.isoformat() for d in s.exceptions), "bookings": list(s.booking_ids)}
                   for s in space.all_series()],
        "waitlist": [{"id": e.id, "resource": e.resource_id, "member": e.member_id, "start": _iso(e.start),
                      "end": _iso(e.end), "attendees": e.attendees, "created_at": _iso(e.created_at)}
                     for e in space.waitlist()],
        "ledger": [{"ts": _iso(e.ts), "member": e.member_id, "month": e.month, "kind": e.kind,
                    "credits": e.credits, "booking": e.booking_id, "note": e.note, "account": e.account}
                   for e in space.ledger()],
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
