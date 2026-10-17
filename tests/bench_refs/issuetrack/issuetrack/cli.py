"""issuetrack CLI: python -m issuetrack [--file PATH] <명령> ..."""

import argparse
import io
import sys
from datetime import date

from issuetrack import csvio, reports, storage
from issuetrack.errors import IssueError
from issuetrack.models import STATUSES


def _date(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"날짜 형식 오류: {text!r} (YYYY-MM-DD)") from None


def build_parser():
    p = argparse.ArgumentParser(prog="issuetrack")
    p.add_argument("--file", default="issues.json")
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("title")
    n.add_argument("--priority", type=int, default=3)
    n.add_argument("--label", action="append", default=[])
    n.add_argument("--assignee")
    n.add_argument("--due")
    s = sub.add_parser("show")
    s.add_argument("id", type=int)
    m = sub.add_parser("move")
    m.add_argument("id", type=int)
    m.add_argument("status")
    a = sub.add_parser("assign")
    a.add_argument("id", type=int)
    a.add_argument("name")
    lab = sub.add_parser("label")
    lab.add_argument("id", type=int)
    lab.add_argument("changes", nargs=argparse.REMAINDER)   # -L 이 옵션으로 읽히지 않게
    d = sub.add_parser("delete")
    d.add_argument("id", type=int)
    ls = sub.add_parser("list")
    ls.add_argument("query", nargs=argparse.REMAINDER)      # -label:bug 같은 부정 항
    e = sub.add_parser("export")
    e.add_argument("path", nargs="?")
    i = sub.add_parser("import")
    i.add_argument("path")
    sub.add_parser("summary")
    return p


def run(args):
    t = storage.load(args.file)
    changed = True
    if args.cmd == "new":
        issue = t.create(args.title, priority=args.priority, labels=args.label, assignee=args.assignee,
                         due=_date(args.due) if args.due else None)
        print(issue.id)
    elif args.cmd == "show":
        changed = False
        x = t.get(args.id)
        for k, v in (("id", x.id), ("title", x.title), ("status", x.status), ("priority", x.priority),
                     ("labels", ",".join(x.labels) or "-"), ("assignee", x.assignee or "-"),
                     ("due", x.due.isoformat() if x.due else "-")):
            print(f"{k}: {v}")
    elif args.cmd == "move":
        t.move(args.id, args.status)
    elif args.cmd == "assign":
        t.update(args.id, assignee=None if args.name == "-" else args.name)
    elif args.cmd == "label":
        add = [c[1:] for c in args.changes if c.startswith("+")]
        remove = [c[1:] for c in args.changes if c.startswith("-")]
        bad = [c for c in args.changes if not c.startswith(("+", "-"))]
        if bad:
            raise ValueError(f"라벨 변경은 +L 또는 -L: {bad[0]!r}")
        t.label(args.id, add=add, remove=remove)
    elif args.cmd == "delete":
        t.delete(args.id)
    elif args.cmd == "list":
        changed = False
        for x in t.search(" ".join(args.query)):
            print(f"{x.id}\t{x.status}\tP{x.priority}\t{x.title}")
    elif args.cmd == "export":
        changed = False
        if args.path:
            with open(args.path, "w", encoding="utf-8", newline="") as f:
                csvio.export_csv(t, f)
        else:
            buf = io.StringIO()
            csvio.export_csv(t, buf)
            sys.stdout.write(buf.getvalue())
    elif args.cmd == "import":
        with open(args.path, encoding="utf-8", newline="") as f:
            ids = csvio.import_csv(t, f)
        print(f"imported {len(ids)}")
    elif args.cmd == "summary":
        changed = False
        for k, v in reports.summary(t).items():
            print(f"{k}\t{v}")
    if changed:
        storage.save(t, args.file)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        run(args)
    except (IssueError, ValueError, OSError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    return 0


__all__ = ["main", "STATUSES"]
