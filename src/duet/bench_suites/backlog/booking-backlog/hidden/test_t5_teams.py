"""#5 팀 크레딧 공유."""

import os
import subprocess
import sys
from datetime import datetime
from decimal import Decimal

import pytest

from booking import AlreadyExists, BookingError, InsufficientCredits, NotFound, Space, UnknownTeam
from booking.invoices import invoice, render_invoice, team_invoice
from booking.reports import credit_usage, team_usage

NOW = datetime(2026, 10, 19, 9, 0)      # 월요일


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def dt(day, hh, mm=0, month=10):
    return datetime(2026, month, day, hh, mm)


@pytest.fixture
def clock():
    return Clock(NOW)


@pytest.fixture
def space(clock):
    s = Space(clock=clock)
    s.add_resource("room-a", "Room A", capacity=6, credits_per_hour=4)
    s.add_resource("big", "Big", capacity=8, credits_per_hour=10)
    s.add_member("alice", "Alice", plan="pro")
    s.add_member("bob", "Bob", plan="pro")
    s.add_member("carol", "Carol")                      # basic 40
    return s


@pytest.fixture
def core(space):
    space.add_team("core", "Core", 50)
    space.join_team("alice", "core")
    return space


# ---------------------------------------------------------------- 팀 관리
def test_add_team_and_list(space):
    t = space.add_team("core", " Core ", 50, "2.50")
    space.add_team("alpha", "Alpha", 0)
    assert (t.id, t.name, t.monthly_credits, t.overage_price, t.members) == ("core", "Core", 50, Decimal("2.50"), [])
    assert [x.id for x in space.teams()] == ["alpha", "core"] and space.team("alpha").overage_price is None


def test_add_team_validation_and_errors(space):
    space.add_team("core", "Core", 50)
    for args in (("Core", "x", 5), ("t1", " ", 5), ("t1", "x", -1), ("t1", "x", "5"), ("t1", "x", 5, "-1"),
                 ("t1", "x", 5, "abc")):
        with pytest.raises(ValueError):
            space.add_team(*args)
    with pytest.raises(AlreadyExists):
        space.add_team("core", "Again", 5)
    with pytest.raises(UnknownTeam):
        space.team("nope")
    assert issubclass(UnknownTeam, NotFound)


def test_join_and_leave(space):
    space.add_team("core", "Core", 50)
    space.add_team("other", "Other", 50)
    space.join_team("bob", "core")
    space.join_team("alice", "core")
    assert space.member("alice").team == "core" and space.team("core").members == ["alice", "bob"]
    with pytest.raises(BookingError):
        space.join_team("alice", "other")
    space.leave_team("alice")
    assert space.member("alice").team is None and space.team("core").members == ["bob"]
    with pytest.raises(BookingError):
        space.leave_team("alice")


# ---------------------------------------------------------------- 청구
def test_team_booking_charges_team(core):
    b = core.book("room-a", "alice", dt(20, 10), dt(20, 12))
    assert b.charged == 8 and core.team_balance("core", "2026-10") == 42
    assert core.balance("alice", "2026-10") == 120
    assert [(r.team_id, r.allowance, r.used, r.balance) for r in team_usage(core, "2026-10")] == [("core", 50, 8, 42)]
    assert {r.member_id: r.used for r in credit_usage(core, "2026-10")}["alice"] == 0


def test_account_fields(core):
    a = core.book("room-a", "alice", dt(20, 10), dt(20, 12))
    b = core.book("room-a", "bob", dt(20, 13), dt(20, 14))
    assert (a.account, b.account) == ("team:core", "member:bob")
    assert [(e.account, e.member_id) for e in core.ledger("alice")] == [("team:core", "alice")]


def test_team_pool_is_shared_and_limited(space):
    space.add_team("core", "Core", 10)
    space.join_team("alice", "core")
    space.join_team("bob", "core")
    space.book("room-a", "alice", dt(20, 10), dt(20, 12))
    with pytest.raises(InsufficientCredits):
        space.book("room-a", "bob", dt(20, 13), dt(20, 14))      # bob 의 pro 플랜 초과 허용과 상관없다
    assert space.team_balance("core", "2026-10") == 2 and len(space.bookings()) == 1


def test_team_overage_allowed(space):
    space.add_team("core", "Core", 10, "1.50")
    space.join_team("bob", "core")
    space.book("room-a", "bob", dt(20, 10), dt(20, 13))          # 12
    assert space.team_balance("core", "2026-10") == -2


def test_series_charges_team_per_month(space):
    space.add_team("core", "Core", 100)
    space.join_team("carol", "core")
    s = space.book_series("room-a", "carol", dt(20, 10), dt(20, 11), count=3)
    assert all(space.booking(i).account == "team:core" for i in s.booking_ids)
    assert space.team_balance("core", "2026-10") == 92 and space.team_balance("core", "2026-11") == 96
    assert space.balance("carol", "2026-10") == 40


def test_series_checks_team_credits(space):
    space.add_team("core", "Core", 5)
    space.join_team("alice", "core")
    with pytest.raises(InsufficientCredits):
        space.book_series("room-a", "alice", dt(20, 10), dt(20, 11), count=2)
    assert space.bookings() == []


def test_waitlist_promotion_charges_team(space, clock):
    space.book("big", "carol", dt(21, 9), dt(21, 13))            # carol 개인 40 다 씀
    b = space.book("big", "alice", dt(20, 10), dt(20, 11))
    space.join_waitlist("big", "carol", dt(20, 10), dt(20, 11))
    space.add_team("core", "Core", 100)
    space.join_team("carol", "core")                              # 계정은 승격 시점의 소속으로
    clock.t = dt(19, 12)
    space.cancel(b.id)
    [nb] = [x for x in space.bookings(member_id="carol") if x.note == "waitlist"]
    assert nb.account == "team:core" and space.team_balance("core", "2026-10") == 90
    assert space.balance("carol", "2026-10") == 0


def test_refund_goes_to_team_after_leaving(core, clock):
    b = core.book("room-a", "alice", dt(23, 10), dt(23, 12))
    early = core.book("room-a", "alice", dt(19, 14), dt(19, 15))
    core.leave_team("alice")
    clock.t = dt(19, 13)
    core.cancel(b.id)                                             # 수수료 0
    core.cancel(early.id)                                         # 수수료 4 (100%)
    assert core.team_balance("core", "2026-10") == 46 and core.balance("alice", "2026-10") == 120
    assert {e.account for e in core.ledger("alice")} == {"team:core"}


def test_move_of_team_booking_charges_team(core):
    b = core.book("room-a", "alice", dt(20, 10), dt(20, 11))
    core.move(b.id, dt(20, 10), dt(20, 12))
    assert core.team_balance("core", "2026-10") == 42 and core.balance("alice", "2026-10") == 120


# ---------------------------------------------------------------- 청구서
def test_member_invoice_excludes_team_bookings(core):
    core.leave_team("alice")
    core.book("room-a", "alice", dt(20, 8), dt(20, 9))
    core.join_team("alice", "core")
    core.book("room-a", "alice", dt(20, 10), dt(20, 12))
    mine = invoice(core, "alice", "2026-10")
    assert [(line.text, line.credits) for line in mine.lines] == [("Room A 08:00-09:00", 4)] and mine.used == 4


def test_render_team_invoice(space, clock):
    space.add_team("core", "Core", 10, "1.50")
    space.join_team("alice", "core")
    space.join_team("bob", "core")
    space.book("room-a", "alice", dt(20, 10), dt(20, 12))
    space.book("room-a", "carol", dt(21, 10), dt(21, 11))         # 팀이 아님
    late = space.book("room-a", "bob", dt(19, 14), dt(19, 15))
    clock.t = dt(19, 13)
    space.cancel(late.id)                                         # 1시간 전: 수수료 4
    inv = team_invoice(space, "core", "2026-10")
    assert (inv.owner, inv.plan, inv.allowance, inv.used, inv.overage, inv.amount) == \
        ("team:core", "team", 10, 12, 2, Decimal("3.00"))
    assert render_invoice(inv) == (
        "청구서 2026-10 · team:core (team)\n"
        "2026-10-19\t취소 수수료 Room A 14:00-15:00 (bob)\t4\n"
        "2026-10-20\tRoom A 10:00-12:00 (alice)\t8\n"
        "사용 12 / 할당 10\n"
        "초과 2 크레딧 · 금액 3.00\n")


# ---------------------------------------------------------------- CLI
def test_cli_team_commands(tmp_path):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "booking", "--db", str(tmp_path / "b.json"), "--now",
                               "2026-10-19T09:00", *args], capture_output=True, text=True, encoding="utf-8", env=env)

    for args in (("resource-add", "room-a", "Room A", "--capacity", "6"), ("member-add", "alice", "Alice"),
                 ("member-add", "bob", "Bob"), ("team-add", "core", "Core", "50", "--overage", "2.5"),
                 ("team-add", "solo", "Solo", "5"), ("team-join", "bob", "core"), ("team-join", "alice", "core")):
        r = cli(*args)
        assert r.returncode == 0 and r.stdout == "", (args, r.stderr)
    assert cli("teams").stdout.splitlines() == ["core\tCore\t50\t2.50\talice,bob", "solo\tSolo\t5\t-\t"]
    assert cli("book", "room-a", "alice", "2026-10-20T10:00", "2026-10-20T12:00").returncode == 0
    assert cli("team-balance", "core").stdout.strip() == "core\t2026-10\t50\t8\t42"
    assert cli("balance", "alice").stdout.strip() == "alice\t2026-10\t40\t0\t40"
    lines = cli("team-invoice", "core", "2026-10").stdout.splitlines()
    assert lines[:2] == ["청구서 2026-10 · team:core (team)", "2026-10-20\tRoom A 10:00-12:00 (alice)\t8"]
    # 기존 명령의 출력 형식은 그대로
    assert cli("members").stdout.splitlines() == ["alice\tAlice\tbasic", "bob\tBob\tbasic"]
    assert cli("list").stdout.splitlines() == ["1\troom-a\talice\t2026-10-20T10:00\t2026-10-20T12:00\tactive\t8"]
    assert cli("team-leave", "bob").returncode == 0
    assert cli("teams").stdout.splitlines()[0] == "core\tCore\t50\t2.50\talice"
    r = cli("team-join", "alice", "solo")
    assert r.returncode == 1 and r.stderr.startswith("오류:")
