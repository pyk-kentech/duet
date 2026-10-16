"""참조 구현: 숨은 테스트 검증용."""

_TABLE = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
          (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


def to_roman(n):
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 3999:
        raise ValueError(f"1~3999 정수가 아님: {n!r}")
    out = []
    for value, sym in _TABLE:
        while n >= value:
            out.append(sym)
            n -= value
    return "".join(out)


_LOOKUP = {to_roman(i): i for i in range(1, 4000)}


def from_roman(s):
    if not isinstance(s, str) or s not in _LOOKUP:
        raise ValueError(f"표준 로마 숫자가 아님: {s!r}")
    return _LOOKUP[s]
