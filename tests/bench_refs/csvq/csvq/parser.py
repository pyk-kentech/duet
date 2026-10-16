from dataclasses import dataclass, field
from decimal import Decimal

from csvq.errors import QueryError
from csvq.lexer import Token, tokenize


@dataclass
class Query:
    columns: list | None            # None = *
    where: tuple | None = None
    order: list = field(default_factory=list)   # [(col, desc)]
    limit: int | None = None


class _Parser:
    def __init__(self, tokens: list[Token]):
        self.t, self.i = tokens, 0

    def peek(self, kind=None, value=None) -> bool:
        tok = self.t[self.i]
        return (kind is None or tok.kind == kind) and (value is None or tok.value == value)

    def take(self, kind, value=None) -> Token:
        if not self.peek(kind, value):
            tok = self.t[self.i]
            raise QueryError(f"{value or kind} 가 와야 하는데 {tok.value or tok.kind!r}")
        tok = self.t[self.i]
        self.i += 1
        return tok

    def query(self) -> Query:
        self.take("keyword", "SELECT")
        if self.peek("punct", "*"):
            self.i += 1
            cols = None
        else:
            cols = [self.take("ident").value]
            while self.peek("punct", ","):
                self.i += 1
                cols.append(self.take("ident").value)
        q = Query(cols)
        if self.peek("keyword", "WHERE"):
            self.i += 1
            q.where = self.or_()
        if self.peek("keyword", "ORDER"):
            self.i += 1
            self.take("keyword", "BY")
            while True:
                col = self.take("ident").value
                desc = False
                if self.peek("keyword", "ASC"):
                    self.i += 1
                elif self.peek("keyword", "DESC"):
                    self.i += 1
                    desc = True
                q.order.append((col, desc))
                if not self.peek("punct", ","):
                    break
                self.i += 1
        if self.peek("keyword", "LIMIT"):
            self.i += 1
            tok = self.take("number")
            if not tok.value.isdigit():
                raise QueryError(f"LIMIT 은 0 이상의 정수: {tok.value}")
            q.limit = int(tok.value)
        self.take("eof")
        return q

    def or_(self):
        node = self.and_()
        while self.peek("keyword", "OR"):
            self.i += 1
            node = ("or", node, self.and_())
        return node

    def and_(self):
        node = self.not_()
        while self.peek("keyword", "AND"):
            self.i += 1
            node = ("and", node, self.not_())
        return node

    def not_(self):
        if self.peek("keyword", "NOT"):
            self.i += 1
            return ("not", self.not_())
        if self.peek("punct", "("):
            self.i += 1
            node = self.or_()
            self.take("punct", ")")
            return node
        col = self.take("ident").value
        op = self.take("op").value
        if op == "<>":
            op = "!="
        if self.peek("number"):
            lit = ("number", Decimal(self.take("number").value))
        else:
            lit = ("string", self.take("string").value)
        return ("cmp", col, op, lit)


def parse(q: str) -> Query:
    return _Parser(tokenize(q)).query()
