import json
from datetime import date, datetime, timedelta

import pytest

from issuetrack import StorageError, Tracker
from issuetrack import storage


def build():
    now = [datetime(2026, 5, 1, 9, 0)]

    def clock():
        return now[0]

    t = Tracker(clock=clock)
    t.create("a", labels=["x", "y"], assignee="kim", due=date(2026, 5, 7))
    t.create("b", priority=1)
    t.create("c")
    now[0] += timedelta(hours=1)
    t.move(1, "doing")
    t.update(2, due=date(2026, 6, 1), title="b2")
    t.label(2, add=["z"])
    t.delete(3)
    return t


def snapshot(t):
    return ([(i.id, i.title, i.status, i.priority, i.labels, i.assignee, i.due, i.created, i.updated) for i in t.issues()],
            [(e.at, e.issue_id, e.field, e.old, e.new) for i in t.issues() for e in t.history(i.id)])


def test_roundtrip_and_version(tmp_path):
    t = build()
    p = tmp_path / "i.json"
    storage.save(t, p)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["version"] == 2
    back = storage.load(p)
    assert snapshot(back) == snapshot(t)
    assert not (tmp_path / "i.json.tmp").exists()


def test_event_value_types_survive(tmp_path):
    t = build()
    p = tmp_path / "i.json"
    storage.save(t, p)
    ev = {(e.field): e for e in storage.load(p).history(2)}
    assert ev["due"].new == date(2026, 6, 1) and isinstance(ev["due"].new, date)
    assert ev["labels"].new == ("z",) and isinstance(ev["labels"].new, tuple)


def test_deleted_id_not_reused_after_load(tmp_path):
    t = build()
    p = tmp_path / "i.json"
    storage.save(t, p)
    back = storage.load(p, clock=lambda: datetime(2026, 5, 2))
    assert back.create("d").id == 4


def test_missing_file_is_empty(tmp_path):
    t = storage.load(tmp_path / "none.json")
    assert t.issues() == [] and t.create("x").id == 1


def test_load_uses_clock(tmp_path):
    p = tmp_path / "i.json"
    storage.save(build(), p)
    back = storage.load(p, clock=lambda: datetime(2030, 1, 1))
    assert back.create("new").created == datetime(2030, 1, 1)


def test_version1(tmp_path):
    p = tmp_path / "old.json"
    p.write_text(json.dumps({"version": 1, "issues": [
        {"id": 3, "title": "old one", "status": "doing", "labels": "Bug, ui", "assignee": "kim", "due": "2026-01-02",
         "created": "2025-12-01T10:00:00"},
        {"id": 7, "title": "older", "status": "open", "labels": "", "assignee": None, "due": None,
         "created": "2025-11-01T08:30:00", "priority": 1},
    ]}), encoding="utf-8")
    t = storage.load(p)
    a, b = t.issues()
    assert (a.id, a.title, a.status, a.priority, a.labels, a.assignee, a.due) == (3, "old one", "doing", 3, ("bug", "ui"), "kim", date(2026, 1, 2))
    assert a.updated == a.created == datetime(2025, 12, 1, 10, 0)
    assert (b.id, b.priority, b.labels, b.due) == (7, 1, (), None)
    assert t.history(3) == []
    assert t.create("next").id == 8


@pytest.mark.parametrize("content", [
    "{not json", json.dumps({"version": 3, "issues": []}), json.dumps({"issues": []}),
    json.dumps({"version": 1, "issues": [{"id": 1, "title": "x", "status": "weird", "labels": "", "created": "2025-01-01T00:00:00"}]}),
    json.dumps({"version": 1, "issues": [{"id": 1, "title": "x", "status": "open", "labels": "", "created": "yesterday"}]}),
    json.dumps([1, 2]),
])
def test_bad_files(tmp_path, content):
    p = tmp_path / "bad.json"
    p.write_text(content, encoding="utf-8")
    with pytest.raises(StorageError):
        storage.load(p)
