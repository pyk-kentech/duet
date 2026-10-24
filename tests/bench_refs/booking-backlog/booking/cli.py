"""booking CLI: ``python -m booking [--db 파일] [--now 시각] <명령> ...``

시각은 ``YYYY-MM-DDTHH:MM``(공백 구분도 됨), 날짜는 ``YYYY-MM-DD``, 월은 ``YYYY-MM``.
``--now`` 를 주면 그 시각을 '지금'으로 쓴다(기본: 실제 현재 시각, 분 단위로 자름).
바꾸는 명령만 파일에 저장한다. 오류는 표준 오류에 ``오류: ...``, 종료 코드 1, 파일은 바꾸지 않는다.
출력 형식은 README 에 있다.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from booking import admin, storage
from booking.errors import BookingError
from booking.export import export_ics
from booking.hours import DEFAULT_HOURS, format_hours
from booking.importer import import_bookings
from booking.invoices import invoice, render_invoice, team_invoice
from booking.reports import agenda, credit_usage, utilization
from booking.timeutil import fmt_dt, month_key, parse_date, parse_dt

CHANGING = {"resource-add", "resource-set", "member-add", "plan", "book", "series", "cancel", "cancel-series", "skip", "move",
            "wait", "unwait", "import", "purge", "team-add", "team-join", "team-leave"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="booking", description="코워킹 스페이스 예약")
    p.add_argument("--db", default="booking.json", help="데이터 파일 (기본: booking.json)")
    p.add_argument("--now", default=None, help="지금 시각 (기본: 실제 현재 시각)")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("resource-add", help="자원 추가")
    a.add_argument("id")
    a.add_argument("name")
    a.add_argument("--kind", default="room", choices=["room", "desk"])
    a.add_argument("--capacity", type=int, default=1)
    a.add_argument("--cph", type=int, default=4, help="시간당 크레딧")
    a.add_argument("--buffer", type=int, default=0, help="버퍼(분)")
    a.add_argument("--hours", default=DEFAULT_HOURS)
    sub.add_parser("resources", help="자원 목록")
    rs = sub.add_parser("resource-set", help="자원 정보 바꾸기")
    rs.add_argument("id")
    rs.add_argument("--name")
    rs.add_argument("--capacity", type=int)
    rs.add_argument("--cph", type=int)
    rs.add_argument("--buffer", type=int)
    rs.add_argument("--hours")

    m = sub.add_parser("member-add", help="회원 추가")
    m.add_argument("id")
    m.add_argument("name")
    m.add_argument("--plan", default="basic")
    sub.add_parser("members", help="회원 목록")
    ta = sub.add_parser("team-add", help="팀 추가")
    ta.add_argument("id")
    ta.add_argument("name")
    ta.add_argument("credits", type=int)
    ta.add_argument("--overage", default=None, help="초과 크레딧당 금액 (없으면 초과 불가)")
    tj = sub.add_parser("team-join", help="팀에 넣기")
    tj.add_argument("member")
    tj.add_argument("team")
    tl = sub.add_parser("team-leave", help="팀에서 빼기")
    tl.add_argument("member")
    sub.add_parser("teams", help="팀 목록")
    tb = sub.add_parser("team-balance", help="팀 크레딧 잔액")
    tb.add_argument("team")
    tb.add_argument("--month")
    ti = sub.add_parser("team-invoice", help="팀 월 청구서")
    ti.add_argument("team")
    ti.add_argument("month")
    pl = sub.add_parser("plan", help="플랜 바꾸기")
    pl.add_argument("member")
    pl.add_argument("plan")

    b = sub.add_parser("book", help="예약")
    b.add_argument("resource")
    b.add_argument("member")
    b.add_argument("start")
    b.add_argument("end")
    b.add_argument("--attendees", type=int, default=1)
    b.add_argument("--note", default="")

    s = sub.add_parser("series", help="반복 예약")
    s.add_argument("resource")
    s.add_argument("member")
    s.add_argument("start")
    s.add_argument("end")
    s.add_argument("--freq", default="weekly", choices=["weekly", "biweekly"])
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--count", type=int)
    g.add_argument("--until")
    s.add_argument("--attendees", type=int, default=1)
    s.add_argument("--note", default="")
    s.add_argument("--skip-conflicts", action="store_true")

    c = sub.add_parser("cancel", help="예약 취소")
    c.add_argument("booking_id", type=int)
    cs = sub.add_parser("cancel-series", help="반복 예약 취소")
    cs.add_argument("series_id", type=int)
    cs.add_argument("--from", dest="from_date")
    sk = sub.add_parser("skip", help="반복 예약의 한 날짜 취소")
    sk.add_argument("series_id", type=int)
    sk.add_argument("date")

    mv = sub.add_parser("move", help="예약 시각 바꾸기")
    mv.add_argument("booking_id", type=int)
    mv.add_argument("start")
    mv.add_argument("end")

    w = sub.add_parser("wait", help="대기 등록")
    w.add_argument("resource")
    w.add_argument("member")
    w.add_argument("start")
    w.add_argument("end")
    w.add_argument("--attendees", type=int, default=1)
    uw = sub.add_parser("unwait", help="대기 취소")
    uw.add_argument("entry_id", type=int)
    wl = sub.add_parser("waitlist", help="대기열")
    wl.add_argument("--resource")

    ls = sub.add_parser("list", help="예약 목록")
    ls.add_argument("--resource")
    ls.add_argument("--member")
    ls.add_argument("--from", dest="from_dt")
    ls.add_argument("--to", dest="to_dt")
    ls.add_argument("--all", action="store_true", help="취소된 예약도")

    f = sub.add_parser("free", help="빈 시작 시각")
    f.add_argument("resource")
    f.add_argument("date")
    f.add_argument("minutes", type=int)

    bal = sub.add_parser("balance", help="크레딧 잔액")
    bal.add_argument("member")
    bal.add_argument("--month")
    us = sub.add_parser("usage", help="회원별 크레딧 사용량")
    us.add_argument("month")
    inv = sub.add_parser("invoice", help="월 청구서")
    inv.add_argument("member")
    inv.add_argument("month")
    rp = sub.add_parser("report", help="가동률")
    rp.add_argument("start")
    rp.add_argument("end")
    rp.add_argument("--resource")
    im = sub.add_parser("import", help="CSV 일괄 예약")
    im.add_argument("file")
    pg = sub.add_parser("purge", help="수수료 없는 지난 취소 예약 지우기")
    pg.add_argument("--before", required=True)
    sub.add_parser("check", help="자가 점검")
    nt = sub.add_parser("notifications", help="알림함")
    nt.add_argument("--member")
    ag = sub.add_parser("agenda", help="하루 일정")
    ag.add_argument("date")
    ag.add_argument("--resource")
    ex = sub.add_parser("export", help="iCalendar 내보내기")
    ex.add_argument("--resource")
    ex.add_argument("--member")
    return p


def _when(text: str) -> datetime:
    """날짜만 주면 그날 00:00."""
    text = text.strip()
    if len(text) == 10:
        d = parse_date(text)
        return datetime(d.year, d.month, d.day)
    return parse_dt(text)


def _booking_line(b) -> str:
    return f"{b.id}\t{fmt_dt(b.start)}\t{fmt_dt(b.end)}\t{b.charged}"


def _cancel_line(c) -> str:
    return f"{c.booking_id}\t{c.fee}\t{c.refund}"


def run(args, out=None) -> None:
    out = out or sys.stdout
    now = parse_dt(args.now) if args.now else datetime.now().replace(second=0, microsecond=0)
    space = storage.load(args.db, clock=lambda: now)
    cmd = args.cmd

    def say(line: str) -> None:
        out.write(line + "\n")

    if cmd == "resource-add":
        space.add_resource(args.id, args.name, kind=args.kind, capacity=args.capacity, credits_per_hour=args.cph,
                           buffer_minutes=args.buffer, hours=args.hours)
    elif cmd == "resources":
        for r in space.resources():
            say(f"{r.id}\t{r.kind}\t{r.capacity}\t{r.credits_per_hour}\t{r.buffer_minutes}\t{format_hours(r.hours)}")
    elif cmd == "resource-set":
        space.update_resource(args.id, name=args.name, capacity=args.capacity, credits_per_hour=args.cph,
                              buffer_minutes=args.buffer, hours=args.hours)
    elif cmd == "member-add":
        space.add_member(args.id, args.name, args.plan)
    elif cmd == "members":
        for mem in space.members():
            say(f"{mem.id}\t{mem.name}\t{mem.plan}")
    elif cmd == "team-add":
        space.add_team(args.id, args.name, args.credits, args.overage)
    elif cmd == "team-join":
        space.join_team(args.member, args.team)
    elif cmd == "team-leave":
        space.leave_team(args.member)
    elif cmd == "teams":
        for t in space.teams():
            price = "-" if t.overage_price is None else f"{t.overage_price:.2f}"
            say(f"{t.id}	{t.name}	{t.monthly_credits}	{price}	{','.join(t.members)}")
    elif cmd == "team-balance":
        month = month_key(args.month) if args.month else month_key(now)
        t = space.team(args.team)
        bal = space.team_balance(t.id, month)
        say(f"{t.id}	{month}	{t.monthly_credits}	{t.monthly_credits - bal}	{bal}")
    elif cmd == "team-invoice":
        out.write(render_invoice(team_invoice(space, args.team, args.month)))
    elif cmd == "plan":
        space.set_plan(args.member, args.plan)
    elif cmd == "book":
        b = space.book(args.resource, args.member, parse_dt(args.start), parse_dt(args.end),
                       attendees=args.attendees, note=args.note)
        say(_booking_line(b))
    elif cmd == "series":
        until = parse_date(args.until) if args.until else None
        s = space.book_series(args.resource, args.member, parse_dt(args.start), parse_dt(args.end), freq=args.freq,
                              count=args.count, until=until, attendees=args.attendees, note=args.note,
                              skip_conflicts=args.skip_conflicts)
        say(f"series\t{s.id}")
        for bid in s.booking_ids:
            say(_booking_line(space.booking(bid)))
        for d in sorted(s.exceptions):
            say(f"skipped\t{d.isoformat()}")
    elif cmd == "cancel":
        say(_cancel_line(space.cancel(args.booking_id)))
    elif cmd == "cancel-series":
        frm = parse_date(args.from_date) if args.from_date else None
        for c in space.cancel_series(args.series_id, from_date=frm):
            say(_cancel_line(c))
    elif cmd == "skip":
        say(_cancel_line(space.skip_occurrence(args.series_id, parse_date(args.date))))
    elif cmd == "move":
        say(_booking_line(space.move(args.booking_id, parse_dt(args.start), parse_dt(args.end))))
    elif cmd == "wait":
        e = space.join_waitlist(args.resource, args.member, parse_dt(args.start), parse_dt(args.end),
                                attendees=args.attendees)
        say(str(e.id))
    elif cmd == "unwait":
        space.leave_waitlist(args.entry_id)
    elif cmd == "waitlist":
        for e in space.waitlist(args.resource):
            say(f"{e.id}\t{e.resource_id}\t{e.member_id}\t{fmt_dt(e.start)}\t{fmt_dt(e.end)}")
    elif cmd == "list":
        frm = _when(args.from_dt) if args.from_dt else None
        to = _when(args.to_dt) if args.to_dt else None
        for b in space.bookings(resource_id=args.resource, member_id=args.member, start=frm, end=to,
                                include_cancelled=args.all):
            say(f"{b.id}\t{b.resource_id}\t{b.member_id}\t{fmt_dt(b.start)}\t{fmt_dt(b.end)}\t{b.status}\t{b.charged}")
    elif cmd == "free":
        for t in space.free_slots(args.resource, parse_date(args.date), args.minutes):
            say(fmt_dt(t))
    elif cmd == "balance":
        month = month_key(args.month) if args.month else month_key(now)
        plan = space.plan_of(args.member)
        bal = space.balance(args.member, month)
        say(f"{args.member}\t{month}\t{plan.monthly_credits}\t{plan.monthly_credits - bal}\t{bal}")
    elif cmd == "usage":
        for row in credit_usage(space, args.month):
            say(f"{row.member_id}\t{row.plan}\t{row.allowance}\t{row.used}\t{row.balance}")
    elif cmd == "invoice":
        out.write(render_invoice(invoice(space, args.member, args.month)))
    elif cmd == "report":
        for row in utilization(space, _when(args.start), _when(args.end), resource_id=args.resource):
            say(f"{row.resource_id}\t{row.open_minutes}\t{row.booked_minutes}\t{row.percent:.1f}")
    elif cmd == "agenda":
        for row in agenda(space, parse_date(args.date), resource_id=args.resource):
            say(f"{row.resource_id}	{fmt_dt(row.start)}	{fmt_dt(row.end)}	{row.member_id}	{row.note}")
    elif cmd == "import":
        try:
            with open(args.file, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            raise ValueError(f"{args.file} 를 읽을 수 없습니다: {e}") from None
        for b in import_bookings(space, text):
            say(_booking_line(b))
    elif cmd == "purge":
        say(str(admin.purge_cancelled(space, _when(args.before))))
    elif cmd == "check":
        problems = admin.check_integrity(space)
        for p in problems:
            say(p)
        if not problems:
            say("ok")
    elif cmd == "notifications":
        for n in space.notifications(args.member):
            say(f"{fmt_dt(n.ts)}	{n.member_id}	{n.kind}	{n.text}")
    elif cmd == "export":
        text = export_ics(space, resource_id=args.resource, member_id=args.member)
        if out is sys.stdout and hasattr(sys.stdout, "buffer"):
            sys.stdout.flush()
            sys.stdout.buffer.write(text.encode("utf-8"))   # CRLF 를 그대로 (텍스트 모드 줄바꿈 변환 피하기)
            sys.stdout.buffer.flush()
        else:
            out.write(text)
    if cmd in CHANGING:
        storage.save(space, args.db)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run(args)
    except (BookingError, ValueError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    return 0
