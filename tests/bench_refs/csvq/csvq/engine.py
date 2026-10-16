import csv
import io
import operator
import re
from decimal import Decimal

from csvq.errors import QueryError
from csvq.parser import parse

_NUM_RE = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")
_OPS = {"=": operator.eq, "!=": operator.ne, "<": operator.lt, "<=": operator.le,
        ">": operator.gt, ">=": operator.ge}


def _load(csv_text):
    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows or not rows[0]:
        raise QueryError("머리글이 없습니다")
    header = rows[0]
    if len(set(header)) != len(header):
        raise QueryError("열 이름이 겹칩니다")
    data = []
    for n, r in enumerate(rows[1:], 2):
        if len(r) > len(header):
            raise QueryError(f"{n}번째 행의 필드가 머리글보다 많습니다")
        data.append(dict(zip(header, r + [""] * (len(header) - len(r)))))
    types = {}
    for col in header:
        vals = [d[col] for d in data if d[col] != ""]
        types[col] = "empty" if not vals else ("number" if all(_NUM_RE.match(v) for v in vals) else "text")
    return header, data, types


def _need(col, types):
    if col not in types:
        raise QueryError(f"없는 열: {col}")


def _check(node, types):
    kind = node[0]
    if kind in ("and", "or"):
        _check(node[1], types)
        _check(node[2], types)
    elif kind == "not":
        _check(node[1], types)
    else:
        _, col, _, (lt, _) = node
        _need(col, types)
        t = types[col]
        want = "number" if lt == "number" else "text"
        if t != "empty" and t != want:
            raise QueryError(f"{col} 은 {t} 열인데 {lt} 값과 비교")


def _key(value, t):
    return Decimal(value) if t == "number" else value


def _eval(node, row, types):
    kind = node[0]
    if kind == "cmp":
        _, col, op, (_, lit) = node
        v = row[col]
        if v == "":
            return None
        return _OPS[op](_key(v, types[col]), lit)
    if kind == "not":
        r = _eval(node[1], row, types)
        return None if r is None else not r
    a, b = _eval(node[1], row, types), _eval(node[2], row, types)
    if kind == "and":
        if a is False or b is False:
            return False
        return None if a is None or b is None else True
    if a is True or b is True:
        return True
    return None if a is None or b is None else False


def query(csv_text, q):
    ast = parse(q)
    header, data, types = _load(csv_text)
    cols = header if ast.columns is None else ast.columns
    for c in cols:
        _need(c, types)
    for c, _ in ast.order:
        _need(c, types)
    if ast.where is not None:
        _check(ast.where, types)
        data = [r for r in data if _eval(ast.where, r, types) is True]
    for col, desc in reversed(ast.order):
        present = [r for r in data if r[col] != ""]
        nulls = [r for r in data if r[col] == ""]
        present.sort(key=lambda r: _key(r[col], types[col]), reverse=desc)
        data = present + nulls
    if ast.limit is not None:
        data = data[:ast.limit]
    return [{c: r[c] for c in cols} for r in data]
