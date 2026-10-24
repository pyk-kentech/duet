from datetime import date, datetime

from booking.export import export_ics
from booking.invoices import invoice, render_invoice
from booking.reports import agenda, credit_usage, utilization


def dt(day, hh, mm=0):
    return datetime(2026, 10, day, hh, mm)


def test_utilization_one_day(space):
    space.book("room-a", "alice", dt(20, 9), dt(20, 12))
    [row] = utilization(space, dt(20, 0), dt(21, 0), resource_id="room-a")
    assert (row.resource_id, row.open_minutes, row.booked_minutes, row.percent) == ("room-a", 720, 180, 25.0)


def test_utilization_all_resources_sorted(space):
    rows = utilization(space, dt(19, 0), dt(26, 0))
    assert [r.resource_id for r in rows] == ["desk-1", "room-a", "room-b"]
    assert rows[1].open_minutes == 5 * 720


def test_credit_usage(space):
    space.book("room-a", "alice", dt(20, 9), dt(20, 10))
    rows = credit_usage(space, "2026-10")
    assert [(r.member_id, r.used, r.balance) for r in rows] == [("alice", 4, 36), ("bob", 0, 120), ("carol", 0, 0)]


def test_invoice_totals(space):
    space.book("room-a", "alice", dt(20, 9), dt(20, 10, 30))
    space.book("room-b", "alice", dt(21, 9), dt(21, 10))
    inv = invoice(space, "alice", "2026-10")
    assert [line.credits for line in inv.lines] == [6, 6]
    assert (inv.used, inv.overage, str(inv.amount)) == (12, 0, "0.00")
    text = render_invoice(inv)
    assert text.splitlines()[0] == "청구서 2026-10 · alice (basic)"


def test_invoice_overage(space):
    space.book("room-b", "carol", dt(20, 9), dt(20, 11))
    inv = invoice(space, "carol", "2026-10")
    assert (inv.used, inv.overage, str(inv.amount)) == (12, 12, "36.00")


def test_export_contains_events(space):
    space.book("room-a", "alice", dt(20, 9), dt(20, 10))
    text = export_ics(space)
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert "DTSTART:20261020T090000" in text and "SUMMARY:Room A (alice)" in text


def test_agenda(space):
    space.book("room-b", "bob", dt(20, 9), dt(20, 10))
    space.book("room-a", "alice", dt(20, 11), dt(20, 12))
    rows = agenda(space, date(2026, 10, 20))
    assert [(r.resource_id, r.member_id) for r in rows] == [("room-a", "alice"), ("room-b", "bob")]
