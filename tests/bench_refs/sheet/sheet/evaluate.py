"""수식 계산: 연산자와 함수."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, localcontext

from sheet.formula import (Binary, Bool, ErrLit, Func, Name, Num, Paren, Percent, Range, Ref, Str, Unary,
                           is_ref_arg, unparen)
from sheet.values import (DIV0, EMPTY, MAX_COL, MAX_ROW, NAME, NUM, NUM_TEXT_RE, VALUE, Error, finite, to_bool,
                          to_num, to_text)


class RangeVal:
    __slots__ = ("c1", "r1", "c2", "r2")

    def __init__(self, c1: int, r1: int, c2: int, r2: int) -> None:
        self.c1, self.r1, self.c2, self.r2 = c1, r1, c2, r2


def scalar(v):
    return VALUE if isinstance(v, RangeVal) else v


def _rank(v) -> int:
    if isinstance(v, bool):
        return 2
    if isinstance(v, str):
        return 1
    return 0


def compare(op: str, a, b) -> bool:
    if a is EMPTY and b is EMPTY:
        a = b = 0.0
    elif a is EMPTY:
        a = False if isinstance(b, bool) else ("" if isinstance(b, str) else 0.0)
    elif b is EMPTY:
        b = False if isinstance(a, bool) else ("" if isinstance(a, str) else 0.0)
    ra, rb = _rank(a), _rank(b)
    if ra != rb:
        x, y = ra, rb
    elif ra == 1:
        x, y = a.lower(), b.lower()
    else:
        x, y = a, b
    if op == "=":
        return x == y
    if op == "<>":
        return x != y
    if op == "<":
        return x < y
    if op == ">":
        return x > y
    if op == "<=":
        return x <= y
    return x >= y


def arith(op: str, a: float, b: float):
    if op == "+":
        return finite(a + b)
    if op == "-":
        return finite(a - b)
    if op == "*":
        return finite(a * b)
    if op == "/":
        if b == 0:
            return DIV0
        return finite(a / b)
    # ^
    if a == 0 and b == 0:
        return NUM
    if a == 0 and b < 0:
        return DIV0
    if a < 0 and not b.is_integer():
        return NUM
    try:
        r = a ** b
    except OverflowError:
        return NUM
    except ZeroDivisionError:
        return DIV0
    if isinstance(r, complex):
        return NUM
    return finite(float(r))


def round_half_away(x: float, d: float) -> float:
    digits = int(d)          # 0 쪽으로 자름
    if digits > 400:
        return x
    if digits < -400:
        return 0.0
    with localcontext() as ctx:
        ctx.prec = 2000
        r = Decimal(repr(x)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return float(r)


# ---------------------------------------------------------------- COUNTIF·SUMIF 조건
_CRIT_OPS = ("<=", ">=", "<>", "<", ">", "=")


def _wild_regex(pat: str) -> re.Pattern:
    out, i = [], 0
    while i < len(pat):
        ch = pat[i]
        if ch == "~" and i + 1 < len(pat) and pat[i + 1] in "*?~":
            out.append(re.escape(pat[i + 1]))
            i += 2
            continue
        if ch == "*":
            out.append(".*")
        elif ch == "?":
            out.append(".")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("".join(out), re.DOTALL)


def make_pred(crit):
    if crit is EMPTY:
        op, operand = "=", ""
    elif isinstance(crit, bool) or isinstance(crit, float):
        op, operand = "=", crit
    else:
        s = crit
        op = "="
        for o in _CRIT_OPS:
            if s.startswith(o):
                op, s = o, s[len(o):]
                break
        if NUM_TEXT_RE.fullmatch(s):
            operand = finite(float(s))
            if isinstance(operand, Error):
                operand = s
        elif s.upper() in ("TRUE", "FALSE"):
            operand = s.upper() == "TRUE"
        else:
            operand = s
    if isinstance(operand, str) and operand != "":
        rx = _wild_regex(operand.lower())
    else:
        rx = None

    def eq(v) -> bool:
        if isinstance(operand, bool):
            return isinstance(v, bool) and v == operand
        if isinstance(operand, float):
            return isinstance(v, float) and v == operand
        if operand == "":
            return v is EMPTY or v == ""
        return isinstance(v, str) and rx.fullmatch(v.lower()) is not None

    def pred(v) -> bool:
        if isinstance(v, Error):
            return False
        if op == "=":
            return eq(v)
        if op == "<>":
            return not eq(v)
        if isinstance(operand, bool):
            if not isinstance(v, bool):
                return False
            x, y = v, operand
        elif isinstance(operand, float):
            if not isinstance(v, float):
                return False
            x, y = v, operand
        else:
            if not isinstance(v, str):
                return False
            x, y = v.lower(), operand.lower()
        if op == "<":
            return x < y
        if op == ">":
            return x > y
        if op == "<=":
            return x <= y
        return x >= y

    return pred


# ---------------------------------------------------------------- 계산기
class Evaluator:
    def __init__(self, sheet) -> None:
        self.sheet = sheet

    # 셀 읽기
    def value_at(self, c: int, r: int):
        return self.sheet._value_at(c, r)

    def iter_rect(self, c1: int, r1: int, c2: int, r2: int):
        """비어 있지 않은 셀을 행 우선으로 (c, r, 값)."""
        return self.sheet._iter_rect(c1, r1, c2, r2)

    def rect_of(self, node) -> tuple[int, int, int, int]:
        n = unparen(node)
        if type(n) is Ref:
            return n.col, n.row, n.col, n.row
        return n.a.col, n.a.row, n.b.col, n.b.row

    def ref_values(self, node):
        """참조 인수의 비어 있지 않은 셀 값들 (행 우선)."""
        for _c, _r, v in self.iter_rect(*self.rect_of(node)):
            yield v

    # 식
    def ev(self, node):
        t = type(node)
        if t is Num:
            return finite(node.value)
        if t is Str:
            return node.value
        if t is Bool:
            return node.value
        if t is ErrLit:
            return Error(node.code)
        if t is Name:
            return NAME
        if t is Ref:
            return self.value_at(node.col, node.row)
        if t is Range:
            return RangeVal(node.a.col, node.a.row, node.b.col, node.b.row)
        if t is Paren:
            return self.ev(node.inner)
        if t is Unary:
            v = scalar(self.ev(node.operand))
            if node.op == "+":
                return 0.0 if v is EMPTY else v
            n = to_num(v)
            return n if isinstance(n, Error) else -n
        if t is Percent:
            n = to_num(scalar(self.ev(node.operand)))
            return n if isinstance(n, Error) else n / 100
        if t is Binary:
            return self.binary(node)
        if t is Func:
            return self.call(node)
        raise TypeError(node)

    def binary(self, node):
        op = node.op
        if op in ("+", "-", "*", "/", "^"):
            a = to_num(scalar(self.ev(node.left)))
            if isinstance(a, Error):
                return a
            b = to_num(scalar(self.ev(node.right)))
            if isinstance(b, Error):
                return b
            return arith(op, a, b)
        if op == "&":
            a = to_text(scalar(self.ev(node.left)))
            if isinstance(a, Error):
                return a
            b = to_text(scalar(self.ev(node.right)))
            if isinstance(b, Error):
                return b
            return a + b
        a = scalar(self.ev(node.left))
        if isinstance(a, Error):
            return a
        b = scalar(self.ev(node.right))
        if isinstance(b, Error):
            return b
        return compare(op, a, b)

    def result(self, node):
        """함수·수식의 최종 값: 범위는 #VALUE!, 빈 칸은 0."""
        v = scalar(self.ev(node))
        return 0.0 if v is EMPTY else v

    # 함수
    def call(self, node: Func):
        name, args = node.name, node.args
        fn = getattr(self, "f_" + name, None)
        if fn is None:
            return NAME
        return fn(args)

    def collect_numbers(self, args):
        nums: list[float] = []
        for a in args:
            if is_ref_arg(a):
                for v in self.ref_values(a):
                    if isinstance(v, Error):
                        return v
                    if isinstance(v, float):
                        nums.append(v)
            else:
                n = to_num(scalar(self.ev(a)))
                if isinstance(n, Error):
                    return n
                nums.append(n)
        return nums

    def f_SUM(self, args):
        nums = self.collect_numbers(args)
        if isinstance(nums, Error):
            return nums
        total = 0.0
        for x in nums:
            total += x
        return finite(total)

    def f_AVERAGE(self, args):
        nums = self.collect_numbers(args)
        if isinstance(nums, Error):
            return nums
        if not nums:
            return DIV0
        total = 0.0
        for x in nums:
            total += x
        return finite(total / len(nums))

    def f_MIN(self, args):
        nums = self.collect_numbers(args)
        if isinstance(nums, Error):
            return nums
        return min(nums) if nums else 0.0

    def f_MAX(self, args):
        nums = self.collect_numbers(args)
        if isinstance(nums, Error):
            return nums
        return max(nums) if nums else 0.0

    def f_COUNT(self, args):
        n = 0
        for a in args:
            if is_ref_arg(a):
                n += sum(1 for v in self.ref_values(a) if isinstance(v, float))
            else:
                v = scalar(self.ev(a))
                if isinstance(v, (float, bool)):
                    n += 1
                elif isinstance(v, str) and isinstance(to_num(v), float):
                    n += 1
        return float(n)

    def f_COUNTA(self, args):
        n = 0
        for a in args:
            if is_ref_arg(a):
                n += sum(1 for _ in self.ref_values(a))
            else:
                self.ev(a)
                n += 1
        return float(n)

    def _logicals(self, args):
        vals: list[bool] = []
        for a in args:
            if is_ref_arg(a):
                for v in self.ref_values(a):
                    if isinstance(v, Error):
                        return v
                    if isinstance(v, bool):
                        vals.append(v)
                    elif isinstance(v, float):
                        vals.append(v != 0)
            else:
                v = scalar(self.ev(a))
                if isinstance(v, Error):
                    return v
                if isinstance(v, bool):
                    vals.append(v)
                elif isinstance(v, float):
                    vals.append(v != 0)
                elif v is EMPTY:
                    vals.append(False)
                else:
                    return VALUE
        if not vals:
            return VALUE
        return vals

    def f_AND(self, args):
        vals = self._logicals(args)
        return vals if isinstance(vals, Error) else all(vals)

    def f_OR(self, args):
        vals = self._logicals(args)
        return vals if isinstance(vals, Error) else any(vals)

    def f_IF(self, args):
        c = to_bool(scalar(self.ev(args[0])))
        if isinstance(c, Error):
            return c
        if c:
            return self.result(args[1])
        if len(args) == 3:
            return self.result(args[2])
        return False

    def f_IFERROR(self, args):
        v = self.result(args[0])
        if isinstance(v, Error):
            return self.result(args[1])
        return v

    def f_NOT(self, args):
        c = to_bool(scalar(self.ev(args[0])))
        return c if isinstance(c, Error) else (not c)

    def f_ROUND(self, args):
        x = to_num(scalar(self.ev(args[0])))
        if isinstance(x, Error):
            return x
        d = to_num(scalar(self.ev(args[1])))
        if isinstance(d, Error):
            return d
        return round_half_away(x, d)

    def f_ABS(self, args):
        x = to_num(scalar(self.ev(args[0])))
        return x if isinstance(x, Error) else abs(x)

    def f_CONCAT(self, args):
        parts: list[str] = []
        for a in args:
            if is_ref_arg(a):
                for v in self.ref_values(a):
                    s = to_text(v)
                    if isinstance(s, Error):
                        return s
                    parts.append(s)
            else:
                s = to_text(scalar(self.ev(a)))
                if isinstance(s, Error):
                    return s
                parts.append(s)
        return "".join(parts)

    def f_LEN(self, args):
        s = to_text(scalar(self.ev(args[0])))
        return s if isinstance(s, Error) else float(len(s))

    def f_UPPER(self, args):
        s = to_text(scalar(self.ev(args[0])))
        return s if isinstance(s, Error) else s.upper()

    def _ref_or_error(self, node):
        if is_ref_arg(node):
            return self.rect_of(node)
        v = scalar(self.ev(node))
        return v if isinstance(v, Error) else VALUE

    def f_COUNTIF(self, args):
        rect = self._ref_or_error(args[0])
        if isinstance(rect, Error):
            return rect
        crit = scalar(self.ev(args[1]))
        if isinstance(crit, Error):
            return crit
        pred = make_pred(crit)
        c1, r1, c2, r2 = rect
        n = nonempty = 0
        for _c, _r, v in self.iter_rect(c1, r1, c2, r2):
            nonempty += 1
            if pred(v):
                n += 1
        if pred(EMPTY):
            n += (c2 - c1 + 1) * (r2 - r1 + 1) - nonempty
        return float(n)

    def f_SUMIF(self, args):
        rect = self._ref_or_error(args[0])
        if isinstance(rect, Error):
            return rect
        crit = scalar(self.ev(args[1]))
        if isinstance(crit, Error):
            return crit
        c1, r1, c2, r2 = rect
        if len(args) == 3:
            srect = self._ref_or_error(args[2])
            if isinstance(srect, Error):
                return srect
            sc, sr = srect[0], srect[1]
        else:
            sc, sr = c1, r1
        w, h = c2 - c1 + 1, r2 - r1 + 1
        pred = make_pred(crit)
        offs: set[tuple[int, int]] = set()
        for c, r, v in self.iter_rect(c1, r1, c2, r2):
            if pred(v):
                offs.add((r - r1, c - c1))
        if pred(EMPTY):
            ec, er = min(sc + w - 1, MAX_COL), min(sr + h - 1, MAX_ROW)
            for c, r, _v in self.iter_rect(sc, sr, ec, er):
                oc, orow = c - sc, r - sr
                if self.value_at(c1 + oc, r1 + orow) is EMPTY:
                    offs.add((orow, oc))
        total = 0.0
        for orow, oc in sorted(offs):
            c, r = sc + oc, sr + orow
            if c > MAX_COL or r > MAX_ROW:
                continue
            v = self.value_at(c, r)
            if isinstance(v, Error):
                return v
            if isinstance(v, float):
                total += v
        return finite(total)
