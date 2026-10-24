"""셀 주소 ↔ 좌표 (열·행 모두 1부터)."""

from __future__ import annotations

import re

from sheet.values import MAX_COL, MAX_ROW

_CELL_RE = re.compile(r"([A-Za-z]{1,3})([1-9][0-9]*)")
_COL_RE = re.compile(r"[A-Za-z]{1,3}")


def col_to_letters(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def letters_to_col(s: str) -> int:
    n = 0
    for ch in s.upper():
        n = n * 26 + ord(ch) - 64
    return n


def parse_cell(ref: str) -> tuple[int, int]:
    m = _CELL_RE.fullmatch(ref) if isinstance(ref, str) else None
    if m:
        col, row = letters_to_col(m.group(1)), int(m.group(2))
        if col <= MAX_COL and row <= MAX_ROW:
            return col, row
    raise ValueError(f"잘못된 셀 주소: {ref!r}")


def parse_area(ref: str) -> tuple[int, int, int, int]:
    if not isinstance(ref, str):
        raise ValueError(f"잘못된 영역: {ref!r}")
    parts = ref.split(":")
    if len(parts) == 1:
        c, r = parse_cell(parts[0])
        return c, r, c, r
    if len(parts) != 2:
        raise ValueError(f"잘못된 영역: {ref!r}")
    a, b = parse_cell(parts[0]), parse_cell(parts[1])
    return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])


def parse_col(s: str) -> int:
    if isinstance(s, str) and _COL_RE.fullmatch(s):
        c = letters_to_col(s)
        if c <= MAX_COL:
            return c
    raise ValueError(f"잘못된 열: {s!r}")
