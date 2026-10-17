import csv
import io
from datetime import date, datetime

import pytest

from issuetrack import CsvFormatError, Tracker
from issuetrack.csvio import export_csv, import_csv

T = datetime(2026, 5, 1, 9, 0)


def test_export_format():
    t = Tracker(clock=lambda: T)
    t.create('Comma, and "quote"', priority=2, labels=["b", "a"], assignee="kim", due=date(2026, 5, 9))
    t.create("plain")
    buf = io.StringIO(newline="")
    export_csv(t, buf)
    text = buf.getvalue()
    assert text.splitlines()[0] == "id,title,status,priority,labels,assignee,due"
    assert text.endswith("\r\n")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[1] == ["1", 'Comma, and "quote"', "open", "2", "a;b", "kim", "2026-05-09"]
    assert rows[2] == ["2", "plain", "open", "3", "", "", ""]


def test_import_roundtrip_and_new_ids():
    src = Tracker(clock=lambda: T)
    src.create("one", labels=["x"], assignee="lee", due=date(2026, 6, 1))
    src.create("two", priority=1)
    buf = io.StringIO(newline="")
    export_csv(src, buf)
    dst = Tracker(clock=lambda: T)
    dst.create("existing")
    ids = import_csv(dst, io.StringIO(buf.getvalue(), newline=""))
    assert ids == [2, 3]
    a = dst.get(2)
    assert (a.title, a.labels, a.assignee, a.due, a.priority, a.status) == ("one", ("x",), "lee", date(2026, 6, 1), 3, "open")
    assert dst.get(3).priority == 1


def test_import_column_order_optional_columns_and_status():
    t = Tracker(clock=lambda: T)
    data = "status,title\r\ndone,finished thing\r\n,fresh\r\n"
    ids = import_csv(t, io.StringIO(data, newline=""))
    assert [t.get(i).status for i in ids] == ["done", "open"]
    [e] = t.history(ids[0])
    assert (e.field, e.old, e.new) == ("created", None, "done")


def test_import_labels_split_and_normalized():
    t = Tracker(clock=lambda: T)
    ids = import_csv(t, io.StringIO("title,labels\r\nx,Bug; UI ;\r\n", newline=""))
    assert t.get(ids[0]).labels == ("bug", "ui")


@pytest.mark.parametrize("data, line", [
    ("title,priority\r\nok,1\r\nbad,9\r\n", 3),
    ("title,due\r\nok,\r\nalso ok,2026-01-01\r\nbad,2026-02-30\r\n", 4),
    ("title,status\r\n,open\r\n", 2),
    ("title,status\r\nx,blocked\r\n", 2),
    ("title,labels\r\nx,ok\r\ny,bad label\r\n", 3),
    ("title,priority\r\nx,high\r\n", 2),
])
def test_import_all_or_nothing(data, line):
    t = Tracker(clock=lambda: T)
    t.create("keep")
    with pytest.raises(CsvFormatError) as ei:
        import_csv(t, io.StringIO(data, newline=""))
    assert f"줄 {line}" in str(ei.value)
    assert [i.title for i in t.issues()] == ["keep"]
    assert t.create("next").id == 2


@pytest.mark.parametrize("data", ["", "status,priority\r\nopen,1\r\n", "title,color\r\nx,red\r\n"])
def test_import_header_errors(data):
    t = Tracker(clock=lambda: T)
    with pytest.raises(CsvFormatError):
        import_csv(t, io.StringIO(data, newline=""))
    assert t.issues() == []
