from datetime import date, datetime, timedelta

import pytest

from issuetrack import QueryError, Tracker


class Clock:
    def __init__(self):
        self.t = datetime(2026, 5, 10, 9, 0)

    def __call__(self):
        return self.t


@pytest.fixture
def t():
    c = Clock()
    tr = Tracker(clock=c)
    tr.create("Login fails on Safari", priority=1, labels=["bug", "ui"], assignee="Kim", due=date(2026, 5, 1))   # 1
    tr.create("Write release notes", priority=3, labels=["docs"], due=date(2026, 5, 20))                         # 2
    tr.create("Refactor login module", priority=2, labels=["tech-debt"], assignee="lee")                         # 3
    tr.create("Fix typo in docs", priority=4, labels=["docs", "bug"], assignee="kim", due=date(2026, 5, 9))      # 4
    tr.create("Old crash", priority=1, labels=["bug"], assignee="park", due=date(2026, 4, 1))                    # 5
    for s in ("doing", "review", "done"):
        c.t += timedelta(hours=1)
        tr.move(5, s)
    c.t += timedelta(hours=1)
    tr.update(2, title="Write release notes v2")
    return tr


def ids(t, q):
    return [i.id for i in t.search(q)]


def test_empty_query_default_order(t):
    assert ids(t, "") == [1, 5, 3, 2, 4]
    assert ids(t, "   ") == [1, 5, 3, 2, 4]


@pytest.mark.parametrize("q, want", [
    ("status:open", [1, 3, 2, 4]),
    ("status:done", [5]),
    ("status:open,done", [1, 5, 3, 2, 4]),
    ("label:bug", [1, 5, 4]),
    ("label:BUG", [1, 5, 4]),
    ("label:bug label:docs", [4]),
    ("assignee:kim", [1, 4]),
    ("assignee:KIM", [1, 4]),
    ("assignee:none", [2]),
    ("priority:1", [1, 5]),
    ("priority=1", [1, 5]),
    ("priority<3", [1, 5, 3]),
    ("priority<=3", [1, 5, 3, 2]),
    ("priority>2", [2, 4]),
    ("priority>=4", [4]),
    ("login", [1, 3]),
    ("LOGIN", [1, 3]),
    ('"release notes"', [2]),
    ('"notes release"', []),
    ("is:open", [1, 3, 2, 4]),
    ("is:overdue", [1, 4]),
    ("due<2026-05-10", [1, 5, 4]),
    ("due:2026-05-20", [2]),
    ("due>=2026-05-09", [2, 4]),
    ("due:none", [3]),
    ("-due:none", [1, 5, 2, 4]),
    ("-label:bug", [3, 2]),
    ('-"release"', [1, 5, 3, 4]),
    ("-login", [5, 2, 4]),
    ("label:docs OR assignee:lee", [3, 2, 4]),
    ("label:bug priority:1 OR status:open label:docs", [1, 5, 2, 4]),
    ("or", [3]),                       # 대문자가 아니면 제목 검색 ("Refact-or")
])
def test_filters(t, q, want):
    assert ids(t, q) == want


def test_due_compare_excludes_missing_due(t):
    assert 3 not in ids(t, "due>2000-01-01") and 3 not in ids(t, "due<2100-01-01")
    assert 3 in ids(t, "-due<2100-01-01")


@pytest.mark.parametrize("q, want", [
    ("sort:id", [1, 2, 3, 4, 5]),
    ("sort:-id", [5, 4, 3, 2, 1]),
    ("sort:priority", [1, 5, 3, 2, 4]),
    ("sort:-priority", [4, 2, 3, 1, 5]),
    ("sort:due", [5, 1, 4, 2, 3]),
    ("sort:-due", [2, 4, 1, 5, 3]),
    ("sort:-updated", [2, 5, 1, 3, 4]),
    ("label:bug sort:-id", [5, 4, 1]),
    ("sort:id label:bug", [1, 4, 5]),
])
def test_sort(t, q, want):
    assert ids(t, q) == want


def test_group_with_only_sort_matches_all(t):
    assert ids(t, "label:docs OR sort:id") == [1, 2, 3, 4, 5]


@pytest.mark.parametrize("q", [
    "OR label:bug", "label:bug OR", "label:bug OR OR status:open", "-", '"unclosed', "foo:bar", "Status:open",
    "status:blocked", "status<open", "priority:5", "priority:x", "priority>0", "due<2026-13-01", "due:soon",
    "is:late", "label:", "sort:name", "sort:id sort:priority", "-sort:id", "assignee:", "sort:-",
])
def test_errors(t, q):
    with pytest.raises(QueryError):
        t.search(q)
