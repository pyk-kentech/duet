"""textstats CLI."""

import argparse
import sys

from textstats import Counts, count

FIELDS = ("lines", "words", "chars", "bytes", "max_line_length")


def parse_args(argv):
    p = argparse.ArgumentParser(prog="textstats", description="줄·단어·글자·바이트 수를 센다")
    p.add_argument("-l", dest="lines", action="store_true", help="줄 수")
    p.add_argument("-w", dest="words", action="store_true", help="단어 수")
    p.add_argument("-m", dest="chars", action="store_true", help="글자 수")
    p.add_argument("-c", dest="bytes", action="store_true", help="바이트 수")
    p.add_argument("-L", "--max-line-length", dest="max_line_length", action="store_true", help="가장 긴 줄의 글자 수")
    p.add_argument("files", nargs="*", metavar="FILE")
    return p.parse_args(argv)


def selected(args):
    chosen = [f for f in FIELDS if getattr(args, f)]
    return chosen or ["lines", "words", "bytes"]


def fmt(c: Counts, fields, name=None):
    vals = " ".join(str(getattr(c, f)) for f in fields)
    return f"{vals} {name}" if name is not None else vals


def main(argv):
    args = parse_args(argv)
    fields = selected(args)
    if not args.files:
        print(fmt(count(sys.stdin.buffer.read()), fields))
        return 0
    total, rc = Counts(), 0
    for name in args.files:
        try:
            data = sys.stdin.buffer.read() if name == "-" else open(name, "rb").read()
        except OSError as e:
            print(f"textstats: {name}: {e.strerror}", file=sys.stderr)
            rc = 1
            continue
        c = count(data)
        total = total + c
        print(fmt(c, fields, None if name == "-" else name))
    if len(args.files) > 1:
        print(fmt(total, fields, "total"))
    return rc
