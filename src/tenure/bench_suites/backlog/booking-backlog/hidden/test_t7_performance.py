"""#7 큰 데이터 성능. 작업마다 따로 프로세스를 띄워 시간을 잰다(읽기 시간 제외).

시간 제한은 작업마다 2초(참조 구현은 0.1초 안팎). 제한의 4배가 지나면 자식 프로세스가 스스로 끝나므로
느린 구현이 채점 시간을 다 쓰지 않는다.
"""

import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import booking

LIMIT = 2.0
ROOMS = 20
MEMBERS = 400
SLOTS = [6, 8, 10, 12, 14, 16, 18]


def _charged(start):
    off = start.weekday() >= 5 or start.hour < 7 or start.hour >= 18
    return 1 if off else 2


def _make(path):
    resources = [{"id": f"room-{i:02d}", "name": f"Room {i:02d}", "kind": "room", "capacity": 8,
                  "credits_per_hour": 2, "buffer_minutes": 15 if i % 4 == 0 else 0, "hours": "mon-sun 06:00-22:00"}
                 for i in range(ROOMS)]
    members = [{"id": f"m{i:03d}", "name": f"Member {i}", "plan": "pro"} for i in range(MEMBERS)]
    bookings, ledger = [], []
    total = 0
    bid = 1
    d = date(2026, 1, 1)
    while d.year == 2026:
        for r in range(ROOMS):
            for h in SLOTS:
                start = datetime(d.year, d.month, d.day, h)
                m = f"m{(bid * 7) % MEMBERS:03d}"
                c = _charged(start)
                total += c
                bookings.append({"id": bid, "resource": f"room-{r:02d}", "member": m, "start": start.isoformat(),
                                 "end": (start + timedelta(hours=1)).isoformat(), "attendees": 1, "note": "",
                                 "status": "active", "series": None, "charged": c, "fee": None,
                                 "created_at": "2025-12-01T00:00:00", "cancelled_at": None})
                ledger.append({"ts": "2025-12-01T00:00:00", "member": m, "month": f"2026-{d.month:02d}",
                               "kind": "charge", "credits": c, "booking": bid, "note": "booking"})
                bid += 1
        d += timedelta(days=1)
    data = {"version": 2, "next_ids": {"booking": bid, "series": 1}, "resources": resources, "members": members,
            "bookings": bookings, "series": [], "ledger": ledger, "notifications": []}
    path.write_text(json.dumps(data), encoding="utf-8")
    return total


CHILD = r'''
import json, os, sys, threading, time
from datetime import date, datetime, timedelta
from booking import storage, Conflict

NOW = datetime(2026, 10, 1, 0, 0)
path, op, limit = sys.argv[1], sys.argv[2], float(sys.argv[3])
t0 = time.perf_counter()
space = storage.load(path, clock=lambda: NOW)
load_s = time.perf_counter() - t0


def day(k):
    return date(2026, 10, 2) + timedelta(days=k)


def at(d, h, m=0):
    return datetime(d.year, d.month, d.day, h, m)


def bid_of(d, room, hour):
    return 1 + ((d - date(2026, 1, 1)).days * 20 + room) * 7 + (hour - 6) // 2


def prep_none():
    return None


def run_util(_):
    from booking.reports import utilization
    rows = utilization(space, datetime(2026, 1, 1), datetime(2027, 1, 1))
    return [[r.resource_id, r.open_minutes, r.booked_minutes, r.percent] for r in rows]


def run_book(_):
    ids = []
    for k in range(2000):
        j = k // 2
        d = date(2026, 10, 1) + timedelta(days=j // 20)
        s0 = at(d, 19, 15) if k % 2 == 0 else at(d, 20, 30)
        ids.append(space.book(f"room-{j % 20:02d}", f"m{k % 400:03d}", s0, s0 + timedelta(hours=1)).id)
    try:
        space.book("room-01", "m001", at(day(0), 8, 30), at(day(0), 9, 30))
        clash = False
    except Conflict:
        clash = True
    return {"n": len(set(ids)), "clash": clash}


def run_series(_):
    n = 0
    spans = [((19, 15), (20, 15)), ((20, 30), (21, 30)), ((21, 45), (22, 0))]
    for k in range(60):
        (h1, m1), (h2, m2) = spans[k // 20]
        s = space.book_series(f"room-{k % 20:02d}", f"m{k:03d}", datetime(2026, 10, 1, h1, m1),
                              datetime(2026, 10, 1, h2, m2), count=52)
        n += len(s.booking_ids)
    try:
        space.book("room-03", "m399", datetime(2026, 10, 8, 21), datetime(2026, 10, 8, 22))
        clash = False
    except Conflict:
        clash = True
    return {"n": n, "clash": clash}


def run_free(_):
    total = 0
    first = None
    for k in range(90):
        slots = space.free_slots("room-01", day(k), 60)
        if first is None:
            first = [s.strftime("%H:%M") for s in slots]
        total += len(slots)
    return {"total": total, "first": first}


def prep_move():
    out = []
    for k in range(3000):
        j = k // 2
        out.append(bid_of(day(j // 20), j % 20, 6 if k % 2 == 0 else 18))
    return out


def run_move(ids):
    for bid in ids:
        b = space.booking(bid)
        space.move(bid, b.start + timedelta(minutes=30), b.end + timedelta(minutes=30))
    ok = space.book("room-05", "m123", at(day(0), 6), at(day(0), 6, 30)).id > 0
    try:
        space.book("room-05", "m123", at(day(0), 7), at(day(0), 8))
        clash = False
    except Conflict:
        clash = True
    return {"n": len(ids), "ok": ok, "clash": clash}


def run_join(_):
    for k in range(4000):
        j = k // 4
        d = date(2026, 11, 1) + timedelta(days=j // 20)
        hour = (8, 10, 12, 14)[k % 4]
        space.join_waitlist(f"room-{j % 20:02d}", f"m{(k + 1) % 400:03d}", at(d, hour), at(d, hour + 1))
    return {"n": len(space.waitlist())}


def prep_cancel():
    ids = []
    for k in range(600):
        d = day(k // 20)
        bid = bid_of(d, k % 20, 10)
        who = f"m{(k + 3) % 400:03d}"
        if who == space.booking(bid).member_id:
            who = "m399"
        space.join_waitlist(f"room-{k % 20:02d}", who, at(d, 10), at(d, 11))
        ids.append(bid)
    return ids


def run_cancel(ids):
    for bid in ids:
        space.cancel(bid)
    promoted = [b for b in space.bookings(start=at(day(0), 0), end=at(day(31), 0)) if b.note == "waitlist"]
    return {"left": len(space.waitlist()), "promoted": len(promoted)}


def run_usage(_):
    from booking.reports import credit_usage
    total = 0
    for m in range(1, 13):
        total += sum(r.used for r in credit_usage(space, f"2026-{m:02d}"))
    return {"used": total}


OPS = {"util": (prep_none, run_util), "book": (prep_none, run_book), "series": (prep_none, run_series),
       "free": (prep_none, run_free), "move": (prep_move, run_move), "join": (prep_none, run_join),
       "cancel": (prep_cancel, run_cancel), "usage": (prep_none, run_usage)}
prep, run = OPS[op]
arg = prep()
killer = threading.Timer(limit * 4, lambda: os._exit(3))
killer.daemon = True
killer.start()
t1 = time.perf_counter()
result = run(arg)
elapsed = time.perf_counter() - t1
sys.stdout.write("\n" + json.dumps({"load": load_s, "elapsed": elapsed, "result": result}) + "\n")
sys.stdout.flush()
os._exit(0)
'''


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    d = tmp_path_factory.mktemp("perf")
    path = d / "year.json"
    total = _make(path)
    (d / "child.py").write_text(CHILD, encoding="utf-8")
    return d, total


def run_op(data, op):
    d, _total = data
    root = str(Path(booking.__file__).resolve().parent.parent)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run([sys.executable, str(d / "child.py"), str(d / "year.json"), op, str(LIMIT)],
                       capture_output=True, text=True, env=env, timeout=180)
    assert r.returncode == 0, f"{op}: 제한 시간 {LIMIT * 4:.0f}초 안에 끝나지 않았거나 실패 (rc={r.returncode})\n{r.stderr[-2000:]}"
    out = json.loads([line for line in r.stdout.splitlines() if line.strip()][-1])
    assert out["load"] < 10, f"load {out['load']:.2f}s"
    assert out["elapsed"] < LIMIT, f"{op}: {out['elapsed']:.2f}s (제한 {LIMIT}s)"
    return out["result"]


def test_utilization_year(data):
    rows = run_op(data, "util")
    pct = round(365 * 7 * 60 * 100 / (365 * 16 * 60), 1)
    assert rows == [[f"room-{i:02d}", 365 * 16 * 60, 365 * 7 * 60, pct] for i in range(ROOMS)]


def test_book_2000(data):
    assert run_op(data, "book") == {"n": 2000, "clash": True}


def test_series_60(data):
    assert run_op(data, "series") == {"n": 60 * 52, "clash": True}


def test_free_slots_90_days(data):
    res = run_op(data, "free")
    assert res["total"] == 90 * 15
    assert res["first"] == ["07:00", "09:00", "11:00", "13:00", "15:00", "17:00", "19:00", "19:15", "19:30", "19:45",
                            "20:00", "20:15", "20:30", "20:45", "21:00"]


def test_move_3000(data):
    assert run_op(data, "move") == {"n": 3000, "ok": True, "clash": True}


def test_join_waitlist_4000(data):
    assert run_op(data, "join") == {"n": 4000}


def test_cancel_600_with_promotion(data):
    assert run_op(data, "cancel") == {"left": 0, "promoted": 600}


def test_credit_usage_12_months(data):
    assert run_op(data, "usage") == {"used": data[1]}
