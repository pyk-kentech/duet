"""Recursive-descent parser producing a small AST."""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import Error
from .lexer import Token, tokenize


# ---------------------------------------------------------------- expressions
@dataclass
class Expr:
    span: tuple[int, int] = field(default=(0, 0), init=False, compare=False)


@dataclass
class Literal(Expr):
    value: object


@dataclass
class Param(Expr):
    index: int


@dataclass
class ColumnRef(Expr):
    table: str | None
    name: str


@dataclass
class Unary(Expr):
    op: str          # '-', '+', 'NOT'
    operand: Expr


@dataclass
class Binary(Expr):
    op: str          # + - * / % || = == != <> < <= > >= AND OR IS ISNOT
    left: Expr
    right: Expr


@dataclass
class Between(Expr):
    expr: Expr
    low: Expr
    high: Expr
    negated: bool


@dataclass
class InList(Expr):
    expr: Expr
    items: list
    negated: bool


@dataclass
class InSelect(Expr):
    expr: Expr
    select: "Select"
    negated: bool


@dataclass
class Exists(Expr):
    select: "Select"


@dataclass
class Subquery(Expr):
    select: "Select"


@dataclass
class Like(Expr):
    expr: Expr
    pattern: Expr
    escape: Expr | None
    negated: bool


@dataclass
class Case(Expr):
    base: Expr | None
    whens: list
    else_: Expr | None


@dataclass
class Cast(Expr):
    expr: Expr
    type_name: str


@dataclass
class FuncCall(Expr):
    name: str
    args: list
    distinct: bool = False
    star: bool = False


# ---------------------------------------------------------------- statements
@dataclass
class ResultCol:
    expr: Expr | None          # None for * / t.*
    alias: str | None = None
    star_table: str | None = None
    star: bool = False


@dataclass
class TableSource:
    name: str
    alias: str | None


@dataclass
class SubquerySource:
    select: "Select"
    alias: str | None


@dataclass
class JoinItem:
    kind: str                  # 'FIRST', 'INNER', 'LEFT', 'CROSS'
    source: object
    on: Expr | None = None
    using: list | None = None


@dataclass
class SelectCore:
    distinct: bool
    columns: list
    from_: list | None
    where: Expr | None
    group_by: list | None
    having: Expr | None


@dataclass
class OrderTerm:
    expr: Expr
    desc: bool
    nulls: str | None          # 'FIRST', 'LAST' or None


@dataclass
class Select:
    cores: list
    ops: list                  # 'UNION', 'UNION ALL', 'INTERSECT', 'EXCEPT'
    order_by: list
    limit: Expr | None
    offset: Expr | None


@dataclass
class CreateTable:
    name: str
    columns: list              # list of (name, type_name or None)


@dataclass
class Insert:
    table: str
    columns: list | None
    rows: list | None          # list of list of Expr
    select: Select | None


@dataclass
class Update:
    table: str
    sets: list                 # list of (column, Expr)
    where: Expr | None


@dataclass
class Delete:
    table: str
    where: Expr | None


AGGREGATES = {"count", "sum", "total", "avg", "min", "max", "group_concat"}


class Parser:
    def __init__(self, sql: str):
        self.sql = sql
        self.toks: list[Token] = tokenize(sql)
        self.pos = 0
        self.param_count = sum(1 for t in self.toks if t.kind == "PARAM")

    # ------------------------------------------------------------ helpers
    @property
    def tok(self) -> Token:
        return self.toks[self.pos]

    def peek(self, k: int = 1) -> Token:
        return self.toks[min(self.pos + k, len(self.toks) - 1)]

    def advance(self) -> Token:
        t = self.toks[self.pos]
        if self.pos < len(self.toks) - 1:
            self.pos += 1
        return t

    def error(self, t: Token | None = None):
        t = t or self.tok
        if t.kind == "EOF":
            raise Error("incomplete input")
        raise Error(f'near "{self.sql[t.start:t.end]}": syntax error')

    def is_kw(self, *words: str) -> bool:
        return self.tok.kind == "KW" and self.tok.value in words

    def is_op(self, *ops: str) -> bool:
        return self.tok.kind == "OP" and self.tok.value in ops

    def accept_kw(self, *words: str) -> bool:
        if self.is_kw(*words):
            self.advance()
            return True
        return False

    def accept_op(self, op: str) -> bool:
        if self.is_op(op):
            self.advance()
            return True
        return False

    def expect_kw(self, word: str) -> Token:
        if not self.is_kw(word):
            self.error()
        return self.advance()

    def expect_op(self, op: str) -> Token:
        if not self.is_op(op):
            self.error()
        return self.advance()

    def ident(self) -> str:
        if self.tok.kind != "ID":
            self.error()
        return self.advance().value

    def prev_end(self) -> int:
        return self.toks[self.pos - 1].end

    # ------------------------------------------------------------ statements
    def at_end_of_statement(self) -> bool:
        return self.tok.kind == "EOF" or self.is_op(";")

    def statement(self):
        if self.is_kw("SELECT"):
            return self.select()
        if self.is_kw("INSERT"):
            return self.insert()
        if self.is_kw("UPDATE"):
            return self.update()
        if self.is_kw("DELETE"):
            return self.delete()
        if self.is_kw("CREATE"):
            return self.create()
        self.error()

    def create(self) -> CreateTable:
        self.expect_kw("CREATE")
        self.expect_kw("TABLE")
        name = self.ident()
        self.expect_op("(")
        cols = []
        while True:
            cname = self.ident()
            words = []
            while self.tok.kind == "ID":
                words.append(self.advance().value)
            type_name = " ".join(words) if words else None
            if words and self.accept_op("("):
                nums = []
                while True:
                    sign = ""
                    if self.is_op("+", "-"):
                        sign = self.advance().value
                    if self.tok.kind != "NUM":
                        self.error()
                    nums.append(sign + self.sql[self.tok.start:self.tok.end])
                    self.advance()
                    if not self.accept_op(","):
                        break
                self.expect_op(")")
                type_name += "(" + ",".join(nums) + ")"
            cols.append((cname, type_name))
            if self.accept_op(","):
                continue
            break
        self.expect_op(")")
        return CreateTable(name, cols)

    def insert(self) -> Insert:
        self.expect_kw("INSERT")
        self.expect_kw("INTO")
        table = self.ident()
        cols = None
        if self.accept_op("("):
            cols = [self.ident()]
            while self.accept_op(","):
                cols.append(self.ident())
            self.expect_op(")")
        if self.accept_kw("VALUES"):
            rows = []
            while True:
                self.expect_op("(")
                row = [self.expr()]
                while self.accept_op(","):
                    row.append(self.expr())
                self.expect_op(")")
                rows.append(row)
                if not self.accept_op(","):
                    break
            return Insert(table, cols, rows, None)
        if self.is_kw("SELECT"):
            return Insert(table, cols, None, self.select())
        self.error()

    def update(self) -> Update:
        self.expect_kw("UPDATE")
        table = self.ident()
        self.expect_kw("SET")
        sets = []
        while True:
            col = self.ident()
            self.expect_op("=")
            sets.append((col, self.expr()))
            if not self.accept_op(","):
                break
        where = self.expr() if self.accept_kw("WHERE") else None
        return Update(table, sets, where)

    def delete(self) -> Delete:
        self.expect_kw("DELETE")
        self.expect_kw("FROM")
        table = self.ident()
        where = self.expr() if self.accept_kw("WHERE") else None
        return Delete(table, where)

    # ------------------------------------------------------------ select
    def select(self) -> Select:
        cores = [self.select_core()]
        ops = []
        while self.is_kw("UNION", "INTERSECT", "EXCEPT"):
            kw = self.advance().value
            if kw == "UNION" and self.accept_kw("ALL"):
                kw = "UNION ALL"
            ops.append(kw)
            cores.append(self.select_core())
        order_by = []
        if self.is_kw("ORDER"):
            self.advance()
            self.expect_kw("BY")
            while True:
                e = self.expr()
                desc = False
                if self.accept_kw("DESC"):
                    desc = True
                else:
                    self.accept_kw("ASC")
                nulls = None
                if self.accept_kw("NULLS"):
                    if self.tok.kind == "ID" and self.tok.value.upper() in ("FIRST", "LAST"):
                        nulls = self.advance().value.upper()
                    else:
                        self.error()
                order_by.append(OrderTerm(e, desc, nulls))
                if not self.accept_op(","):
                    break
        limit = offset = None
        if self.accept_kw("LIMIT"):
            limit = self.expr()
            if self.accept_kw("OFFSET"):
                offset = self.expr()
            elif self.accept_op(","):
                offset = limit
                limit = self.expr()
        if self.is_kw("UNION", "INTERSECT", "EXCEPT") and (order_by or limit is not None):
            kw = self.tok.value
            raise Error(f"{'ORDER BY' if order_by else 'LIMIT'} clause should come after {kw} not before")
        return Select(cores, ops, order_by, limit, offset)

    def select_core(self) -> SelectCore:
        self.expect_kw("SELECT")
        distinct = False
        if self.accept_kw("DISTINCT"):
            distinct = True
        else:
            self.accept_kw("ALL")
        cols = [self.result_col()]
        while self.accept_op(","):
            cols.append(self.result_col())
        from_ = None
        if self.accept_kw("FROM"):
            from_ = self.from_clause()
        where = self.expr() if self.accept_kw("WHERE") else None
        group_by = having = None
        if self.is_kw("GROUP"):
            self.advance()
            self.expect_kw("BY")
            group_by = [self.expr()]
            while self.accept_op(","):
                group_by.append(self.expr())
        if self.accept_kw("HAVING"):
            having = self.expr()
        return SelectCore(distinct, cols, from_, where, group_by, having)

    def result_col(self) -> ResultCol:
        if self.accept_op("*"):
            return ResultCol(None, star=True)
        if self.tok.kind == "ID" and self.peek().kind == "OP" and self.peek().value == "." \
                and self.peek(2).kind == "OP" and self.peek(2).value == "*":
            t = self.advance().value
            self.advance()
            self.advance()
            return ResultCol(None, star=True, star_table=t)
        e = self.expr()
        alias = None
        if self.accept_kw("AS"):
            if self.tok.kind == "STR":
                alias = self.advance().value
            else:
                alias = self.ident()
        elif self.tok.kind == "ID":
            alias = self.advance().value
        return ResultCol(e, alias)

    def from_clause(self) -> list:
        items = [JoinItem("FIRST", self.table_source())]
        while True:
            if self.accept_op(","):
                items.append(JoinItem("CROSS", self.table_source()))
                continue
            kind = None
            if self.is_kw("JOIN"):
                self.advance()
                kind = "INNER"
            elif self.is_kw("INNER"):
                self.advance()
                self.expect_kw("JOIN")
                kind = "INNER"
            elif self.is_kw("CROSS"):
                self.advance()
                self.expect_kw("JOIN")
                kind = "CROSS"
            elif self.is_kw("LEFT"):
                self.advance()
                self.accept_kw("OUTER")
                self.expect_kw("JOIN")
                kind = "LEFT"
            if kind is None:
                break
            src = self.table_source()
            item = JoinItem(kind, src)
            if self.accept_kw("ON"):
                item.on = self.expr()
            elif self.accept_kw("USING"):
                self.expect_op("(")
                item.using = [self.ident()]
                while self.accept_op(","):
                    item.using.append(self.ident())
                self.expect_op(")")
            items.append(item)
        return items

    def table_source(self):
        if self.is_op("("):
            self.advance()
            sel = self.select()
            self.expect_op(")")
            alias = self.opt_alias()
            return SubquerySource(sel, alias)
        name = self.ident()
        return TableSource(name, self.opt_alias())

    def opt_alias(self) -> str | None:
        if self.accept_kw("AS"):
            return self.ident()
        if self.tok.kind == "ID":
            return self.advance().value
        return None

    # ------------------------------------------------------------ expressions
    def expr(self) -> Expr:
        return self.or_expr()

    def _mk(self, node: Expr, start: int) -> Expr:
        node.span = (start, self.prev_end())
        return node

    def or_expr(self) -> Expr:
        start = self.tok.start
        left = self.and_expr()
        while self.accept_kw("OR"):
            right = self.and_expr()
            left = self._mk(Binary("OR", left, right), start)
        return left

    def and_expr(self) -> Expr:
        start = self.tok.start
        left = self.not_expr()
        while self.accept_kw("AND"):
            right = self.not_expr()
            left = self._mk(Binary("AND", left, right), start)
        return left

    def not_expr(self) -> Expr:
        start = self.tok.start
        if self.accept_kw("NOT"):
            operand = self.not_expr()
            return self._mk(Unary("NOT", operand), start)
        return self.equality()

    def equality(self) -> Expr:
        start = self.tok.start
        left = self.relational()
        while True:
            if self.is_op("=", "==", "!=", "<>"):
                op = self.advance().value
                op = {"==": "=", "<>": "!="}.get(op, op)
                right = self.relational()
                left = self._mk(Binary(op, left, right), start)
                continue
            if self.is_kw("IS"):
                self.advance()
                neg = self.accept_kw("NOT")
                right = self.relational()
                left = self._mk(Binary("ISNOT" if neg else "IS", left, right), start)
                continue
            neg = False
            if self.is_kw("NOT") and self.peek().kind == "KW" and self.peek().value in ("IN", "LIKE", "BETWEEN"):
                self.advance()
                neg = True
            if self.accept_kw("IN"):
                self.expect_op("(")
                if self.is_kw("SELECT"):
                    sel = self.select()
                    self.expect_op(")")
                    left = self._mk(InSelect(left, sel, neg), start)
                else:
                    items = []
                    if not self.is_op(")"):
                        items.append(self.expr())
                        while self.accept_op(","):
                            items.append(self.expr())
                    self.expect_op(")")
                    left = self._mk(InList(left, items, neg), start)
                continue
            if self.accept_kw("LIKE"):
                pattern = self.relational()
                esc = None
                if self.accept_kw("ESCAPE"):
                    esc = self.relational()
                left = self._mk(Like(left, pattern, esc, neg), start)
                continue
            if self.accept_kw("BETWEEN"):
                low = self.relational()
                self.expect_kw("AND")
                high = self.relational()
                left = self._mk(Between(left, low, high, neg), start)
                continue
            if neg:
                self.error()
            return left

    def relational(self) -> Expr:
        start = self.tok.start
        left = self.additive()
        while self.is_op("<", "<=", ">", ">="):
            op = self.advance().value
            right = self.additive()
            left = self._mk(Binary(op, left, right), start)
        return left

    def additive(self) -> Expr:
        start = self.tok.start
        left = self.multiplicative()
        while self.is_op("+", "-"):
            op = self.advance().value
            right = self.multiplicative()
            left = self._mk(Binary(op, left, right), start)
        return left

    def multiplicative(self) -> Expr:
        start = self.tok.start
        left = self.concat()
        while self.is_op("*", "/", "%"):
            op = self.advance().value
            right = self.concat()
            left = self._mk(Binary(op, left, right), start)
        return left

    def concat(self) -> Expr:
        start = self.tok.start
        left = self.unary()
        while self.is_op("||"):
            self.advance()
            right = self.unary()
            left = self._mk(Binary("||", left, right), start)
        return left

    def unary(self) -> Expr:
        start = self.tok.start
        if self.is_op("-", "+"):
            op = self.advance().value
            operand = self.unary()
            return self._mk(Unary(op, operand), start)
        return self.primary()

    def primary(self) -> Expr:
        t = self.tok
        start = t.start
        if t.kind == "NUM":
            self.advance()
            return self._mk(Literal(t.value), start)
        if t.kind == "STR":
            self.advance()
            return self._mk(Literal(t.value), start)
        if t.kind == "PARAM":
            self.advance()
            return self._mk(Param(t.value), start)
        if t.kind == "KW":
            if t.value == "NULL":
                self.advance()
                return self._mk(Literal(None), start)
            if t.value == "EXISTS":
                self.advance()
                self.expect_op("(")
                sel = self.select()
                self.expect_op(")")
                return self._mk(Exists(sel), start)
            if t.value == "CASE":
                return self.case_expr()
            if t.value == "CAST":
                self.advance()
                self.expect_op("(")
                e = self.expr()
                self.expect_kw("AS")
                words = []
                while self.tok.kind == "ID":
                    words.append(self.advance().value)
                if not words:
                    self.error()
                tn = " ".join(words)
                if self.accept_op("("):
                    nums = []
                    while True:
                        if self.is_op("+", "-"):
                            self.advance()
                        if self.tok.kind != "NUM":
                            self.error()
                        nums.append(self.sql[self.tok.start:self.tok.end])
                        self.advance()
                        if not self.accept_op(","):
                            break
                    self.expect_op(")")
                    tn += "(" + ",".join(nums) + ")"
                self.expect_op(")")
                return self._mk(Cast(e, tn), start)
            self.error()
        if t.kind == "OP" and t.value == "(":
            self.advance()
            if self.is_kw("SELECT"):
                sel = self.select()
                self.expect_op(")")
                return self._mk(Subquery(sel), start)
            e = self.expr()
            self.expect_op(")")
            e.span = (start, self.prev_end())
            return e
        if t.kind == "ID":
            name = self.advance().value
            if self.is_op("(") and not t.quoted:
                self.advance()
                if self.accept_op("*"):
                    self.expect_op(")")
                    return self._mk(FuncCall(name.lower(), [], star=True), start)
                distinct = self.accept_kw("DISTINCT")
                if not distinct:
                    self.accept_kw("ALL")
                args = []
                if not self.is_op(")"):
                    args.append(self.expr())
                    while self.accept_op(","):
                        args.append(self.expr())
                self.expect_op(")")
                return self._mk(FuncCall(name.lower(), args, distinct=distinct), start)
            if self.is_op("."):
                self.advance()
                col = self.ident()
                return self._mk(ColumnRef(name, col), start)
            return self._mk(ColumnRef(None, name), start)
        self.error()

    def case_expr(self) -> Expr:
        start = self.tok.start
        self.expect_kw("CASE")
        base = None
        if not self.is_kw("WHEN"):
            base = self.expr()
        whens = []
        while self.accept_kw("WHEN"):
            w = self.expr()
            self.expect_kw("THEN")
            whens.append((w, self.expr()))
        if not whens:
            self.error()
        else_ = self.expr() if self.accept_kw("ELSE") else None
        self.expect_kw("END")
        return self._mk(Case(base, whens, else_), start)


def parse_one(sql: str):
    """Exactly one statement (an optional trailing ';' is allowed)."""
    p = Parser(sql)
    if p.tok.kind == "EOF":
        raise Error("empty statement")
    stmt = p.statement()
    if p.accept_op(";"):
        while p.accept_op(";"):
            pass
        if p.tok.kind != "EOF":
            raise Error("You can only execute one statement at a time.")
    elif p.tok.kind != "EOF":
        p.error()
    return stmt, p.param_count


def parse_script(sql: str) -> list:
    p = Parser(sql)
    if p.param_count:
        raise Error("parameters are not allowed in executescript")
    stmts = []
    while True:
        while p.accept_op(";"):
            pass
        if p.tok.kind == "EOF":
            break
        stmts.append(p.statement())
        if p.tok.kind == "EOF":
            break
        if not p.accept_op(";"):
            p.error()
    return stmts
