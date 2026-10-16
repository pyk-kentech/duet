import re
from dataclasses import dataclass

from csvq.errors import QueryError

KEYWORDS = {"SELECT", "WHERE", "ORDER", "BY", "ASC", "DESC", "LIMIT", "AND", "OR", "NOT"}

_TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<number>-?[0-9]+(?:\.[0-9]+)?)
  | (?P<string>'(?:[^']|'')*')
  | (?P<qident>"(?:[^"]|"")*")
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op><=|>=|!=|<>|=|<|>)
  | (?P<punct>[,()*])
""", re.VERBOSE)


@dataclass
class Token:
    kind: str     # keyword ident number string op punct eof
    value: str


def tokenize(q: str) -> list[Token]:
    out, pos = [], 0
    while pos < len(q):
        m = _TOKEN_RE.match(q, pos)
        if not m:
            raise QueryError(f"알 수 없는 글자: {q[pos:pos + 10]!r}")
        pos = m.end()
        kind = m.lastgroup
        text = m.group(kind)
        if kind == "ws":
            continue
        if kind == "ident":
            if text.upper() in KEYWORDS:
                out.append(Token("keyword", text.upper()))
            else:
                out.append(Token("ident", text))
        elif kind == "qident":
            out.append(Token("ident", text[1:-1].replace('""', '"')))
        elif kind == "string":
            out.append(Token("string", text[1:-1].replace("''", "'")))
        else:
            out.append(Token(kind, text))
    out.append(Token("eof", ""))
    return out
