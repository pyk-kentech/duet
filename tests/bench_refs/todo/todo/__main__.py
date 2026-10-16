import argparse
import sys

from todo import StoreError, TodoStore


def main(argv=None):
    p = argparse.ArgumentParser(prog="todo")
    p.add_argument("--file", default="todo.json")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("words", nargs="+")
    li = sub.add_parser("list")
    li.add_argument("--all", action="store_true")
    for name in ("done", "rm"):
        sub.add_parser(name).add_argument("id", type=int)
    args = p.parse_args(argv)
    try:
        s = TodoStore(args.file)
    except StoreError as e:
        print(f"파일이 깨졌습니다: {e}", file=sys.stderr)
        return 3
    try:
        if args.cmd == "add":
            print(f"added {s.add(' '.join(args.words))}")
        elif args.cmd == "list":
            for x in s.items(include_done=args.all):
                print(f"{x['id']}. [{'x' if x['done'] else ' '}] {x['title']}")
        elif args.cmd == "done":
            s.done(args.id)
        else:
            s.remove(args.id)
    except ValueError:
        print("빈 제목", file=sys.stderr)
        return 2
    except KeyError:
        print(f"없는 id: {args.id}", file=sys.stderr)
        return 1
    return 0


sys.exit(main())
