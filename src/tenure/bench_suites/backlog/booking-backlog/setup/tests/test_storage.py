import json
from datetime import date, datetime

import pytest

from booking import StorageError
from booking import storage


def dt(day, hh, mm=0):
    return datetime(2026, 10, day, hh, mm)


def test_roundtrip(space, clock, tmp_path):
    space.book("room-a", "alice", dt(20, 10), dt(20, 11), note="메모")
    s = space.book_series("room-b", "bob", dt(21, 10), dt(21, 11), count=2)
    b = space.book("desk-1", "carol", dt(22, 10), dt(22, 11))
    space.cancel(b.id)
    path = tmp_path / "b.json"
    storage.save(space, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["bookings"]) == 4
    again = storage.load(path, clock=clock)
    assert [(x.id, x.start, x.status, x.charged) for x in again.bookings(include_cancelled=True)] == \
        [(x.id, x.start, x.status, x.charged) for x in space.bookings(include_cancelled=True)]
    assert again.series(s.id).booking_ids == s.booking_ids
    assert again.balance("alice", "2026-10") == space.balance("alice", "2026-10")
    assert again.resource("desk-1").hours == space.resource("desk-1").hours
    nb = again.book("room-a", "alice", dt(23, 10), dt(23, 11))
    assert nb.id == 5


def test_missing_file_is_empty(tmp_path):
    sp = storage.load(tmp_path / "none.json")
    assert sp.resources() == [] and sp.bookings() == []


def test_bad_files(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{nope", encoding="utf-8")
    with pytest.raises(StorageError):
        storage.load(p)
    p.write_text(json.dumps({"version": 99}), encoding="utf-8")
    with pytest.raises(StorageError):
        storage.load(p)
