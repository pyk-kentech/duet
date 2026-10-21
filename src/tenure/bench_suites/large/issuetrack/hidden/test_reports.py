from datetime import date, datetime, timedelta

from issuetrack import Tracker
from issuetrack import reports


class Clock:
    def __init__(self):
        self.t = datetime(2026, 5, 1, 9, 0)

    def __call__(self):
        return self.t


def test_summary_all_statuses():
    t = Tracker(clock=Clock())
    assert reports.summary(t) == {"open": 0, "doing": 0, "review": 0, "done": 0, "closed": 0}
    t.create("a")
    t.create("b")
    t.move(2, "closed")
    assert list(reports.summary(t).items()) == [("open", 1), ("doing", 0), ("review", 0), ("done", 0), ("closed", 1)]


def test_workload_order_and_none_last():
    t = Tracker(clock=Clock())
    for who in ["kim", "lee", "lee", "ahn", None, None, None, "park"]:
        t.create("x", assignee=who)
    t.update(8, assignee="park")
    t.move(8, "doing")
    t.move(8, "review")
    t.move(8, "done")          # park 은 열린 이슈가 없어 빠진다
    assert reports.workload(t) == [("lee", 2), ("ahn", 1), ("kim", 1), ("(none)", 3)]


def test_workload_empty():
    assert reports.workload(Tracker(clock=Clock())) == []


def test_cycle_time_first_doing_to_first_done():
    c = Clock()
    t = Tracker(clock=c)
    t.create("a", assignee="kim")
    t.create("b", assignee="kim")
    assert reports.cycle_time(t, 1) is None
    c.t += timedelta(hours=1)
    t.move(1, "doing")
    c.t += timedelta(hours=1)
    t.move(1, "open")
    c.t += timedelta(hours=1)
    t.move(1, "doing")
    assert reports.cycle_time(t, 1) is None
    c.t += timedelta(hours=2)
    t.move(1, "review")
    t.move(1, "done")
    c.t += timedelta(days=1)
    t.move(1, "doing")
    t.move(1, "review")
    t.move(1, "done")
    assert reports.cycle_time(t, 1) == timedelta(hours=4)


def test_throughput_counts_each_done():
    c = Clock()
    t = Tracker(clock=c)
    t.create("a", assignee="k")
    t.create("b", assignee="k")
    for i in (1, 2):
        for s in ("doing", "review", "done"):
            t.move(i, s)
    c.t += timedelta(days=2)
    t.move(1, "doing")
    t.move(1, "review")
    t.move(1, "done")
    got = reports.throughput(t, date(2026, 4, 30), date(2026, 5, 3))
    assert got == {date(2026, 4, 30): 0, date(2026, 5, 1): 2, date(2026, 5, 2): 0, date(2026, 5, 3): 1}
