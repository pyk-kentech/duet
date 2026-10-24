from datetime import date, datetime, timedelta

import pytest

from issuetrack import STATUSES, Event, InvalidTransition, IssueError, NotFound, Tracker
from issuetrack import CsvFormatError, QueryError, StorageError


class Clock:
    def __init__(self, t=datetime(2026, 5, 1, 9, 0)):
        self.t = t

    def __call__(self):
        return self.t

    def tick(self, minutes=1):
        self.t += timedelta(minutes=minutes)


def make():
    c = Clock()
    return Tracker(clock=c), c


def test_statuses_and_errors():
    assert STATUSES == ("open", "doing", "review", "done", "closed")
    for e in (NotFound, InvalidTransition, QueryError, StorageError, CsvFormatError):
        assert issubclass(e, IssueError)
    assert issubclass(IssueError, Exception) and not issubclass(IssueError, ValueError)


def test_create_normalizes():
    t, c = make()
    i = t.create("  Fix login  ", priority=2, labels=["Bug", "ui", "bug"], assignee=" kim ", due=date(2026, 5, 3))
    assert (i.id, i.title, i.status, i.priority, i.labels, i.assignee, i.due) == (
        1, "Fix login", "open", 2, ("bug", "ui"), "kim", date(2026, 5, 3))
    assert i.created == i.updated == c.t
    assert t.create("second").id == 2
    assert t.create("x").priority == 3 and t.create("y").labels == () and t.get(4).assignee is None


@pytest.mark.parametrize("kw", [
    {"title": ""}, {"title": "   "}, {"title": "x" * 121}, {"priority": 0}, {"priority": 5}, {"priority": True},
    {"priority": "2"}, {"labels": ["bad label"]}, {"labels": ["a" * 21]}, {"labels": ["é"]}, {"assignee": ""},
    {"assignee": "  "}, {"due": datetime(2026, 5, 1, 10, 0)}, {"due": "2026-05-01"},
])
def test_create_validation(kw):
    t, _ = make()
    args = {"title": "ok", **kw}
    title = args.pop("title")
    with pytest.raises(ValueError):
        t.create(title, **args)
    assert t.issues() == []


def test_title_120_ok():
    t, _ = make()
    assert len(t.create("x" * 120).title) == 120


def test_ids_never_reused():
    t, _ = make()
    t.create("a")
    t.create("b")
    t.delete(2)
    assert t.create("c").id == 3
    assert [i.id for i in t.issues()] == [1, 3]


def test_get_delete_not_found():
    t, _ = make()
    for call in (lambda: t.get(1), lambda: t.delete(1), lambda: t.history(1), lambda: t.move(1, "doing"),
                 lambda: t.update(1, title="x"), lambda: t.label(1, add=["a"])):
        with pytest.raises(NotFound):
            call()


def test_created_event():
    t, c = make()
    t.create("a")
    [e] = t.history(1)
    assert isinstance(e, Event) and (e.at, e.issue_id, e.field, e.old, e.new) == (c.t, 1, "created", None, "open")


def test_update_events_only_for_changes():
    t, c = make()
    t.create("a", priority=3)
    created = t.get(1).updated
    c.tick()
    t.update(1, priority=3, title=" a ")
    assert t.history(1)[1:] == [] and t.get(1).updated == created
    t.update(1, priority=1, assignee="lee", due=date(2026, 6, 1))
    ev = [(e.field, e.old, e.new) for e in t.history(1)[1:]]
    assert sorted(ev) == sorted([("priority", 3, 1), ("assignee", None, "lee"), ("due", None, date(2026, 6, 1))])
    assert t.get(1).updated == c.t
    c.tick()
    t.update(1, assignee=None, due=None)
    assert t.get(1).assignee is None and t.get(1).due is None


@pytest.mark.parametrize("kw", [{"status": "done"}, {"labels": ["x"]}, {"id": 5}, {"priority": 9}, {"due": datetime(2026, 1, 1)}])
def test_update_rejects(kw):
    t, _ = make()
    t.create("a")
    with pytest.raises(ValueError):
        t.update(1, **kw)


def test_label_add_then_remove():
    t, c = make()
    t.create("a", labels=["x"])
    c.tick()
    t.label(1, add=["Y", "z"], remove=["z", "nope"])
    assert t.get(1).labels == ("x", "y")
    e = t.history(1)[-1]
    assert (e.field, e.old, e.new) == ("labels", ("x",), ("x", "y"))
    n = len(t.history(1))
    t.label(1, add=["x"], remove=["nope"])
    assert len(t.history(1)) == n
    with pytest.raises(ValueError):
        t.label(1, add=["bad label"])


def test_transitions_table():
    allowed = {"open": {"doing", "closed"}, "doing": {"open", "review"}, "review": {"doing", "done"},
               "done": {"doing", "closed"}, "closed": {"open"}}
    path = {"open": [], "doing": ["doing"], "review": ["doing", "review"], "done": ["doing", "review", "done"],
            "closed": ["closed"]}
    for start, nexts in allowed.items():
        for target in STATUSES:
            t, _ = make()
            t.create("a", assignee="kim")
            for s in path[start]:
                t.move(1, s)
            if target in nexts:
                t.move(1, target)
                assert t.get(1).status == target
            else:
                with pytest.raises(InvalidTransition):
                    t.move(1, target)


def test_move_requires_assignee_for_doing_and_unknown_status():
    t, c = make()
    t.create("a")
    with pytest.raises(InvalidTransition):
        t.move(1, "doing")
    with pytest.raises(ValueError):
        t.move(1, "blocked")
    t.update(1, assignee="kim")
    c.tick()
    t.move(1, "doing")
    e = t.history(1)[-1]
    assert (e.field, e.old, e.new, e.at) == ("status", "open", "doing", c.t) and t.get(1).updated == c.t


def test_delete_removes_events():
    t, _ = make()
    t.create("a")
    t.create("b")
    t.delete(1)
    assert all(e.issue_id == 2 for e in t.history(2))
    with pytest.raises(NotFound):
        t.history(1)
