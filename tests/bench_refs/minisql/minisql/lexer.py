"""Tokenizer. Every token keeps its source offsets so result column names can use the original text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import Error

KEYWORDS = {
    "SELECT", "DISTINCT", "ALL", "FROM", "WHERE", "GROUP", "BY", "HAVING", "ORDER", "ASC", "DESC",
    "NULLS", "LIMIT", "OFFSET", "AS", "JOIN", "INNER", "LEFT", "OUTER", "CROSS", "ON", "USING",
    "UNION", "INTERSECT", "EXCEPT", "INSERT", "INTO", "VALUES", "UPDATE", "SET", "DELETE", "CREATE",
    "TABLE", "AND", "OR", "NOT", "NULL", "IS", "IN", "BETWEEN", "LIKE", "ESCAPE", "EXISTS", "CASE",
    "WHEN", "THEN", "ELSE", "END", "CAST",
}

OPERATORS = ["||", "==", "!=", "<>", "<=", ">=", "(", ")", ",", ";", ".", "*", "+", "-", "/", "%", "=", "<", ">"]

_NUM = re.compile(r"(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?")
_IDENT = re.compile(r"[A-Za-z_\u0080-￿][A-Za-z0-9_$\u0080-￿]*")
_SPACE = " \t\n\r\f\v"


@dataclass
class Token:
    kind: str          # KW, ID, NUM, STR, PARAM, OP, EOF
    value: object
    start: int
    end: int
    quoted: bool = False


def tokenize(sql: str) -> list[Token]:
    toks: list[Token] = []
    i, n = 0, len(sql)
    params = 0
    while i < n:
        c = sql[i]
        if c in _SPACE:
            i += 1
            continue
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c == "'":
            j = i + 1
            buf = []
            while True:
                if j >= n:
                    raise Error(f'unrecognized token: "{sql[i:]}"')
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        buf.append("'")
                        j += 2
                        continue
                    break
                buf.append(sql[j])
                j += 1
            toks.append(Token("STR", "".join(buf), i, j + 1))
            i = j + 1
            continue
        if c == '"':
            j = i + 1
            buf = []
            while True:
                if j >= n:
                    raise Error(f'unrecognized token: "{sql[i:]}"')
                if sql[j] == '"':
                    if j + 1 < n and sql[j + 1] == '"':
                        buf.append('"')
                        j += 2
                        continue
                    break
                buf.append(sql[j])
                j += 1
            toks.append(Token("ID", "".join(buf), i, j + 1, quoted=True))
            i = j + 1
            continue
        if c.isdigit() or (c == "." and i + 1 < n and sql[i + 1].isdigit()):
            m = _NUM.match(sql, i)
            text = m.group(0)
            end = m.end()
            if end < n and (sql[end].isalnum() or sql[end] == "_"):
                raise Error(f'unrecognized token: "{sql[i:end + 1]}"')
            if m.group(2) is None and m.group(3) is None and "." not in text:
                v = int(text)
                value: object = v if -2**63 <= v < 2**63 else float(text)
            else:
                value = float(text)
            toks.append(Token("NUM", value, i, end))
            i = end
            continue
        m = _IDENT.match(sql, i)
        if m:
            word = m.group(0)
            up = word.upper()
            if up in KEYWORDS:
                toks.append(Token("KW", up, i, m.end()))
            else:
                toks.append(Token("ID", word, i, m.end()))
            i = m.end()
            continue
        if c == "?":
            toks.append(Token("PARAM", params, i, i + 1))
            params += 1
            i += 1
            continue
        for op in OPERATORS:
            if sql.startswith(op, i):
                toks.append(Token("OP", op, i, i + len(op)))
                i += len(op)
                break
        else:
            raise Error(f'unrecognized token: "{c}"')
    toks.append(Token("EOF", None, n, n))
    return toks
