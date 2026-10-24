"""수식: 토큰 → 구문 트리, 정규화된 글자로 되돌리기, 참조 바꿔 쓰기."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Callable

from sheet.refs import col_to_letters, letters_to_col
from sheet.values import ERROR_CODES, MAX_COL, MAX_ROW, FormulaError

_NUM_RE = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_WORD_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_REF_RE = re.compile(r"(\$?)([A-Za-z]{1,3})(\$?)([1-9][0-9]*)")
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_WORD_START = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$")
_DIGITS = set("0123456789")
_SPACES = set(" \t\r\n")
_OPS1 = set("+-*/^&=<>%(),:")

ARITY = {
    "SUM": (1, None), "AVERAGE": (1, None), "MIN": (1, None), "MAX": (1, None),
    "COUNT": (1, None), "COUNTA": (1, None), "AND": (1, None), "OR": (1, None), "CONCAT": (1, None),
    "IF": (2, 3), "IFERROR": (2, 2), "ROUND": (2, 2), "NOT": (1, 1), "ABS": (1, 1),
    "LEN": (1, 1), "UPPER": (1, 1), "COUNTIF": (2, 2), "SUMIF": (2, 3),
}


# ---------------------------------------------------------------- 구문 트리
@dataclass(frozen=True)
class Num:
    value: float
    text: str


@dataclass(frozen=True)
class Str:
    value: str


@dataclass(frozen=True)
class Bool:
    value: bool


@dataclass(frozen=True)
class ErrLit:
    code: str


@dataclass(frozen=True)
class Name:
    name: str


@dataclass(frozen=True)
class Ref:
    col: int
    row: int
    col_abs: bool
    row_abs: bool


@dataclass(frozen=True)
class Range:
    a: Ref   # 왼쪽 위
    b: Ref   # 오른쪽 아래


@dataclass(frozen=True)
class Func:
    name: str
    args: tuple


@dataclass(frozen=True)
class Unary:
    op: str
    operand: object


@dataclass(frozen=True)
class Percent:
    operand: object


@dataclass(frozen=True)
class Binary:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class Paren:
    inner: object


def make_range(p: Ref, q: Ref) -> Range:
    """모서리 정규화: 열·행마다 따로 작은 쪽(과 그 $)이 앞. 같으면 쓴 순서."""
    if p.col <= q.col:
        c1, ca1, c2, ca2 = p.col, p.col_abs, q.col, q.col_abs
    else:
        c1, ca1, c2, ca2 = q.col, q.col_abs, p.col, p.col_abs
    if p.row <= q.row:
        r1, ra1, r2, ra2 = p.row, p.row_abs, q.row, q.row_abs
    else:
        r1, ra1, r2, ra2 = q.row, q.row_abs, p.row, p.row_abs
    return Range(Ref(c1, r1, ca1, ra1), Ref(c2, r2, ca2, ra2))


# ---------------------------------------------------------------- 토큰
@dataclass(frozen=True)
class Tok:
    kind: str     # NUM STR BOOL ERR REF FUNC NAME OP
    text: str
    value: object = None


def tokenize(src: str) -> list[Tok]:
    toks: list[Tok] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c in _SPACES:
            i += 1
            continue
        if c in _DIGITS or (c == "." and i + 1 < n and src[i + 1] in _DIGITS):
            m = _NUM_RE.match(src, i)
            toks.append(Tok("NUM", m.group().upper(), float(m.group())))
            i = m.end()
            continue
        if c == '"':
            j, buf = i + 1, []
            while True:
                if j >= n:
                    raise FormulaError("닫히지 않은 문자열")
                if src[j] == '"':
                    if j + 1 < n and src[j + 1] == '"':
                        buf.append('"')
                        j += 2
                        continue
                    j += 1
                    break
                buf.append(src[j])
                j += 1
            toks.append(Tok("STR", src[i:j], "".join(buf)))
            i = j
            continue
        if c == "#":
            for code in ERROR_CODES:
                if src[i:i + len(code)].upper() == code:
                    toks.append(Tok("ERR", code))
                    i += len(code)
                    break
            else:
                raise FormulaError(f"알 수 없는 오류 값: {src[i:]!r}")
            continue
        if c in _WORD_START:
            m = _WORD_RE.match(src, i)
            w, j = m.group(), m.end()
            if j < n and src[j] == "(":
                if not _NAME_RE.fullmatch(w):
                    raise FormulaError(f"잘못된 함수 이름: {w!r}")
                toks.append(Tok("FUNC", w.upper()))
                i = j
                continue
            rm = _REF_RE.fullmatch(w)
            if rm:
                col, row = letters_to_col(rm.group(2)), int(rm.group(4))
                if col <= MAX_COL and row <= MAX_ROW:
                    toks.append(Tok("REF", w.upper(), Ref(col, row, bool(rm.group(1)), bool(rm.group(3)))))
                    i = j
                    continue
            up = w.upper()
            if up in ("TRUE", "FALSE"):
                toks.append(Tok("BOOL", up, up == "TRUE"))
            elif _NAME_RE.fullmatch(w):
                toks.append(Tok("NAME", up))
            else:
                raise FormulaError(f"잘못된 낱말: {w!r}")
            i = j
            continue
        two = src[i:i + 2]
        if two in ("<=", ">=", "<>"):
            toks.append(Tok("OP", two))
            i += 2
            continue
        if c in _OPS1:
            toks.append(Tok("OP", c))
            i += 1
            continue
        raise FormulaError(f"알 수 없는 글자: {c!r}")
    return toks


# ---------------------------------------------------------------- 파서
class _Parser:
    def __init__(self, toks: list[Tok]) -> None:
        self.toks = toks
        self.i = 0

    def peek(self) -> Tok | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def is_op(self, *ops: str) -> bool:
        t = self.peek()
        return t is not None and t.kind == "OP" and t.text in ops

    def take(self) -> Tok:
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, op: str) -> None:
        if not self.is_op(op):
            raise FormulaError(f"'{op}' 가 필요하다")
        self.i += 1

    def parse(self):
        if not self.toks:
            raise FormulaError("빈 수식")
        e = self.expr()
        if self.peek() is not None:
            raise FormulaError(f"남는 토큰: {self.peek().text!r}")
        return e

    def expr(self):
        left = self.concat()
        while self.is_op("=", "<>", "<", ">", "<=", ">="):
            op = self.take().text
            left = Binary(op, left, self.concat())
        return left

    def concat(self):
        left = self.add()
        while self.is_op("&"):
            self.take()
            left = Binary("&", left, self.add())
        return left

    def add(self):
        left = self.mul()
        while self.is_op("+", "-"):
            op = self.take().text
            left = Binary(op, left, self.mul())
        return left

    def mul(self):
        left = self.power()
        while self.is_op("*", "/"):
            op = self.take().text
            left = Binary(op, left, self.power())
        return left

    def power(self):
        left = self.pct()
        while self.is_op("^"):
            self.take()
            left = Binary("^", left, self.pct())
        return left

    def pct(self):
        e = self.unary()
        while self.is_op("%"):
            self.take()
            e = Percent(e)
        return e

    def unary(self):
        if self.is_op("+", "-"):
            op = self.take().text
            return Unary(op, self.unary())
        return self.primary()

    def primary(self):
        t = self.peek()
        if t is None:
            raise FormulaError("식이 끝났다")
        k = t.kind
        if k == "NUM":
            self.take()
            return Num(t.value, t.text)
        if k == "STR":
            self.take()
            return Str(t.value)
        if k == "BOOL":
            self.take()
            return Bool(t.value)
        if k == "ERR":
            self.take()
            return ErrLit(t.text)
        if k == "NAME":
            self.take()
            return Name(t.text)
        if k == "REF":
            self.take()
            if self.is_op(":"):
                self.take()
                t2 = self.peek()
                if t2 is None or t2.kind != "REF":
                    raise FormulaError("범위의 두 번째 모서리가 셀 참조가 아니다")
                self.take()
                return make_range(t.value, t2.value)
            return t.value
        if k == "FUNC":
            self.take()
            self.expect("(")
            args = []
            if not self.is_op(")"):
                args.append(self.expr())
                while self.is_op(","):
                    self.take()
                    args.append(self.expr())
            self.expect(")")
            if t.text in ARITY:
                lo, hi = ARITY[t.text]
                if len(args) < lo or (hi is not None and len(args) > hi):
                    raise FormulaError(f"{t.text} 인수 개수가 맞지 않다")
            return Func(t.text, tuple(args))
        if k == "OP" and t.text == "(":
            self.take()
            e = self.expr()
            self.expect(")")
            return Paren(e)
        raise FormulaError(f"뜻밖의 토큰: {t.text!r}")


def parse_formula(src: str):
    return _Parser(tokenize(src)).parse()


# ---------------------------------------------------------------- 되돌리기
def ref_text(r: Ref) -> str:
    return f"{'$' if r.col_abs else ''}{col_to_letters(r.col)}{'$' if r.row_abs else ''}{r.row}"


def render(node) -> str:
    t = type(node)
    if t is Num:
        return node.text
    if t is Str:
        return '"' + node.value.replace('"', '""') + '"'
    if t is Bool:
        return "TRUE" if node.value else "FALSE"
    if t is ErrLit:
        return node.code
    if t is Name:
        return node.name
    if t is Ref:
        return ref_text(node)
    if t is Range:
        return ref_text(node.a) + ":" + ref_text(node.b)
    if t is Func:
        return node.name + "(" + ",".join(render(a) for a in node.args) + ")"
    if t is Unary:
        return node.op + render(node.operand)
    if t is Percent:
        return render(node.operand) + "%"
    if t is Binary:
        return render(node.left) + node.op + render(node.right)
    if t is Paren:
        return "(" + render(node.inner) + ")"
    raise TypeError(node)


# ---------------------------------------------------------------- 참조 바꿔 쓰기
def map_refs(node, f_ref: Callable[[Ref], object], f_range: Callable[[Range], object]):
    t = type(node)
    if t is Ref:
        return f_ref(node)
    if t is Range:
        return f_range(node)
    if t is Func:
        return Func(node.name, tuple(map_refs(a, f_ref, f_range) for a in node.args))
    if t is Unary:
        return Unary(node.op, map_refs(node.operand, f_ref, f_range))
    if t is Percent:
        return Percent(map_refs(node.operand, f_ref, f_range))
    if t is Binary:
        return Binary(node.op, map_refs(node.left, f_ref, f_range), map_refs(node.right, f_ref, f_range))
    if t is Paren:
        return Paren(map_refs(node.inner, f_ref, f_range))
    return node


def walk(node):
    """모든 노드를 돈다."""
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        t = type(n)
        if t is Func:
            stack.extend(n.args)
        elif t is Unary or t is Percent:
            stack.append(n.operand)
        elif t is Binary:
            stack.extend((n.left, n.right))
        elif t is Paren:
            stack.append(n.inner)


def unparen(node):
    while type(node) is Paren:
        node = node.inner
    return node


def is_ref_arg(node) -> bool:
    return type(unparen(node)) in (Ref, Range)


def shift_ref(r: Ref, dc: int, dr: int, honor_abs: bool) -> Ref | None:
    c = r.col if (honor_abs and r.col_abs) else r.col + dc
    w = r.row if (honor_abs and r.row_abs) else r.row + dr
    if 1 <= c <= MAX_COL and 1 <= w <= MAX_ROW:
        return replace(r, col=c, row=w)
    return None
