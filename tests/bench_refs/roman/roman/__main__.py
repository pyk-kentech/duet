import sys

from roman import from_roman, to_roman


def main(argv):
    if len(argv) != 1:
        print("사용법: python -m roman <값>", file=sys.stderr)
        return 1
    v = argv[0]
    try:
        print(to_roman(int(v)) if v.isdigit() else from_roman(v))
    except ValueError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    return 0


sys.exit(main(sys.argv[1:]))
