"""값 종류: 오류 값, 빈 칸 표시, 숫자 정규화·글자 변환."""

from __future__ import annotations

import math
import re

MAX_COL = 16384      # XFD
MAX_ROW = 1048576

ERROR_CODES = ("#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#N/A", "#NUM!")

NUM_TEXT_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


class FormulaError(ValueError):
    """수식 문법 오류 (set 이 낸다)."""


class Error:
    """셀의 오류 값. code 로 비교한다."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Error) and other.code == self.code

    def __hash__(self) -> int:
        return hash(("sheet.Error", self.code))

    def __repr__(self) -> str:
        return f"Error({self.code!r})"

    def __str__(self) -> str:
        return self.code


DIV0 = Error("#DIV/0!")
VALUE = Error("#VALUE!")
REF = Error("#REF!")
NAME = Error("#NAME?")
NA = Error("#N/A")
NUM = Error("#NUM!")
CYCLE = Error("#CYCLE!")


class _Empty:
    __slots__ = ()

    def __repr__(self) -> str:
        return "EMPTY"


EMPTY = _Empty()


def out(v):
    """내부 값(숫자는 float) → get 이 돌려주는 값."""
    if isinstance(v, float):
        return int(v) if v.is_integer() else v
    return v


def num_text(x: float) -> str:
    n = out(x)
    return str(n) if isinstance(n, int) else repr(n)


def finite(x: float):
    return x if math.isfinite(x) else NUM


def to_num(v):
    if isinstance(v, Error):
        return v
    if v is EMPTY:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, float):
        return v
    if isinstance(v, str):
        s = v.strip()
        if NUM_TEXT_RE.fullmatch(s):
            return finite(float(s))
        return VALUE
    return VALUE   # 범위


def to_text(v):
    if isinstance(v, Error):
        return v
    if v is EMPTY:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return num_text(v)
    if isinstance(v, str):
        return v
    return VALUE


def to_bool(v):
    """IF·NOT 의 조건."""
    if isinstance(v, Error):
        return v
    if v is EMPTY:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return v != 0
    return VALUE
