"""Compiler and executor.

Statements are compiled into Python closures before anything runs, so name errors are raised even
when tables are empty. At run time an environment ``env`` is a tuple of frames (one per nested
SELECT level, innermost last); a frame is a tuple of column values (plus aggregate values for
aggregate queries).
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field

from . import functions as F
from . import parser as P
from .errors import Error
from .values import (
    BLOB, INTEGER, NUMERIC, REAL, TEXT, I64_MAX, I64_MIN, apply_cmp_affinity, apply_storage_affinity,
    compare, comparison_affinity, prefix_numeric, real_to_int_if_exact, sql_bool, to_int, to_number,
    to_real, to_text, truth, type_affinity,
)


# ====================================================================== storage
@dataclass
class Table:
    name: str
    columns: list
    affs: list
    rows: list = field(default_factory=list)


# ====================================================================== scopes
@dataclass
class Source:
    name: str
    columns: list
    affs: list
    offset: int
    hidden: set = field(default_factory=set)


class AggCollector:
    def __init__(self, width: int):
        self.width = width
        self.slots: list = []   # (name, star, distinct, arg_fn, sep_fn)

    def add(self, slot) -> int:
        self.slots.append(slot)
        return self.width + len(self.slots) - 1


class Scope:
    def __init__(self, sources: list, parent: "Scope | None"):
        self.sources = sources
        self.parent = parent
        self.width = sum(len(s.columns) for s in sources)
        self.aliases: list = []          # (name, Expr) of the SELECT list
        self.alias_active = False
        self.agg_active: AggCollector | None = None
        self.agg_clause = ""
        self.correlated = False

    def lookup(self, table: str | None, name: str) -> list:
        hits = []
        lname = name.lower()
        ltable = table.lower() if table is not None else None
        for src in self.sources:
            if ltable is not None and src.name.lower() != ltable:
                continue
            for j, c in enumerate(src.columns):
                if c.lower() == lname:
                    if ltable is None and j in src.hidden:
                        continue
                    hits.append((src.offset + j, src.affs[j], c))
        return hits


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _int_literal(e):
    if isinstance(e, P.Literal) and isinstance(e.value, int):
        return e.value
    if isinstance(e, P.Unary) and e.op in ("-", "+") and isinstance(e.operand, P.Literal) \
            and isinstance(e.operand.value, int):
        return -e.operand.value if e.op == "-" else e.operand.value
    return None


def _walk_aggs(e) -> bool:
    """True if expression contains an aggregate call (not looking inside subqueries)."""
    if e is None:
        return False
    if isinstance(e, P.FuncCall):
        if F.is_aggregate_call(e.name, len(e.args), e.star):
            return True
        return any(_walk_aggs(a) for a in e.args)
    if isinstance(e, (P.Literal, P.Param, P.ColumnRef, P.Subquery, P.Exists)):
        return False
    if isinstance(e, P.Unary):
        return _walk_aggs(e.operand)
    if isinstance(e, P.Binary):
        return _walk_aggs(e.left) or _walk_aggs(e.right)
    if isinstance(e, P.Between):
        return _walk_aggs(e.expr) or _walk_aggs(e.low) or _walk_aggs(e.high)
    if isinstance(e, P.InList):
        return _walk_aggs(e.expr) or any(_walk_aggs(i) for i in e.items)
    if isinstance(e, P.InSelect):
        return _walk_aggs(e.expr)
    if isinstance(e, P.Like):
        return _walk_aggs(e.expr) or _walk_aggs(e.pattern) or _walk_aggs(e.escape)
    if isinstance(e, P.Case):
        return _walk_aggs(e.base) or _walk_aggs(e.else_) or any(_walk_aggs(w) or _walk_aggs(t) for w, t in e.whens)
    if isinstance(e, P.Cast):
        return _walk_aggs(e.expr)
    return False


# ====================================================================== operators
def _arith(op, a, b):
    if a is None or b is None:
        return None
    a = to_number(a)
    b = to_number(b)
    if isinstance(a, int) and isinstance(b, int):
        if op == "+":
            r = a + b
        elif op == "-":
            r = a - b
        elif op == "*":
            r = a * b
        elif op == "/":
            if b == 0:
                return None
            q = abs(a) // abs(b)
            r = q if (a < 0) == (b < 0) else -q
        else:
            if b == 0:
                return None
            r = abs(a) % abs(b)
            return -r if a < 0 else r
        if I64_MIN <= r <= I64_MAX:
            return r
    fa, fb = float(a), float(b)
    if op == "+":
        r = fa + fb
    elif op == "-":
        r = fa - fb
    elif op == "*":
        r = fa * fb
    elif op == "/":
        if fb == 0.0:
            return None
        r = fa / fb
    else:
        ia, ib = to_int(fa), to_int(fb)
        if ib == 0:
            return None
        if ib == -1:
            ib = 1
        m = abs(ia) % abs(ib)
        r = float(-m if ia < 0 else m)
    if r != r:
        return None
    return r


def _concat(a, b):
    if a is None or b is None:
        return None
    return to_text(a) + to_text(b)


def _negate(v):
    if v is None:
        return None
    n = to_number(v)
    if isinstance(n, int):
        if n == I64_MIN:
            return float(-n)
        return -n
    return -n


_LIKE_CACHE: dict = {}


def _like_regex(pattern: str, esc: str | None):
    key = (pattern, esc)
    rx = _LIKE_CACHE.get(key)
    if rx is not None:
        return rx
    out = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if esc is not None and c == esc:
            i += 1
            if i >= len(pattern):
                out.append("(?!)")
                break
            c = pattern[i]
            out.append(_like_char(c))
        elif c == "%":
            out.append(".*")
        elif c == "_":
            out.append(".")
        else:
            out.append(_like_char(c))
        i += 1
    rx = re.compile("".join(out), re.DOTALL)
    if len(_LIKE_CACHE) > 1000:
        _LIKE_CACHE.clear()
    _LIKE_CACHE[key] = rx
    return rx


def _like_char(c: str) -> str:
    if "a" <= c <= "z" or "A" <= c <= "Z":
        return "[" + c.lower() + c.upper() + "]"
    return re.escape(c)


def _cast(v, aff):
    if v is None:
        return None
    if aff == INTEGER:
        return to_int(v)
    if aff == REAL:
        return to_real(v)
    if aff == TEXT:
        return to_text(v)
    if aff == NUMERIC:
        if isinstance(v, (int, float)):
            return v
        n = prefix_numeric(v)
        if isinstance(n, float):
            return real_to_int_if_exact(n)
        return n
    return v


def _and(a, b):
    if a is False or b is False:
        return 0
    if a is None or b is None:
        return None
    return 1


def _cmp_result(op: str, c: int) -> int:
    if op == "=":
        return 1 if c == 0 else 0
    if op == "!=":
        return 1 if c != 0 else 0
    if op == "<":
        return 1 if c < 0 else 0
    if op == "<=":
        return 1 if c <= 0 else 0
    if op == ">":
        return 1 if c > 0 else 0
    return 1 if c >= 0 else 0


def _compare_op(op, a, b, aff):
    if a is None or b is None:
        return None
    a = apply_cmp_affinity(a, aff)
    b = apply_cmp_affinity(b, aff)
    return _cmp_result(op, compare(a, b))


def _limit_value(v) -> int:
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v == int(v):
        return int(v)
    if isinstance(v, str):
        from .values import full_numeric
        n = full_numeric(v)
        if isinstance(n, int):
            return n
        if isinstance(n, float) and n == int(n):
            return int(n)
    raise Error("datatype mismatch")


def _sort_cmp(specs):
    def cmp(x, y):
        for (desc, nulls), a, b in zip(specs, x, y):
            if a is None or b is None:
                if a is None and b is None:
                    continue
                nulls_first = (nulls == "FIRST") if nulls else (not desc)
                if a is None:
                    return -1 if nulls_first else 1
                return 1 if nulls_first else -1
            c = compare(a, b)
            if c:
                return -c if desc else c
        return 0
    return cmp


def _dedupe(rows):
    return list(dict.fromkeys(rows))


# ====================================================================== plans
class CorePlan:
    def __init__(self):
        self.names: list = []
        self.affs: list = []
        self.outs: list = []
        self.from_steps: list = []
        self.has_from = False
        self.where = None
        self.is_agg = False
        self.group = None
        self.having = None
        self.agg: AggCollector | None = None
        self.width = 0
        self.distinct = False
        self.order_keys: list = []      # ('col', idx) or ('fn', fn)
        self.scope: Scope | None = None

    def source_rows(self, env):
        rows = [()]
        for step in self.from_steps:
            right = step["rows"](env)
            cond = step["cond"]
            kind = step["kind"]
            width = step["width"]
            new = []
            for lr in rows:
                matched = False
                for rr in right:
                    comb = lr + rr
                    if cond is None or truth(cond(env + (comb,))) is True:
                        new.append(comb)
                        matched = True
                if kind == "LEFT" and not matched:
                    new.append(lr + (None,) * width)
            rows = new
        return rows

    def produce(self, env, with_keys: bool):
        rows = self.source_rows(env)
        if self.where is not None:
            w = self.where
            rows = [r for r in rows if truth(w(env + (r,))) is True]
        if self.is_agg:
            frames = self._group_frames(env, rows)
        else:
            frames = rows
        out = []
        outs = self.outs
        keys = self.order_keys if with_keys else []
        for fr in frames:
            e2 = env + (fr,)
            vals = tuple(f(e2) for f in outs)
            if keys:
                k = tuple(vals[x] if kind == "col" else x(e2) for kind, x in keys)
            else:
                k = ()
            out.append((vals, k))
        if self.distinct:
            seen = set()
            uniq = []
            for vals, k in out:
                if vals in seen:
                    continue
                seen.add(vals)
                uniq.append((vals, k))
            out = uniq
        return out

    def _group_frames(self, env, rows):
        if self.group is not None:
            groups: dict = {}
            for r in rows:
                e2 = env + (r,)
                key = tuple(g(e2) for g in self.group)
                groups.setdefault(key, []).append(r)
            glist = list(groups.values())
        else:
            glist = [rows]
        frames = []
        for grows in glist:
            rep = grows[0] if grows else (None,) * self.width
            aggvals = []
            for name, star, distinct, arg_fn, sep_fn in self.agg.slots:
                if star:
                    values = [1] * len(grows)
                    seps = None
                else:
                    values = []
                    seps = [] if sep_fn is not None else None
                    for r in grows:
                        e2 = env + (r,)
                        values.append(arg_fn(e2))
                        if sep_fn is not None:
                            seps.append(sep_fn(e2))
                    if distinct:
                        seen = set()
                        uv = []
                        for v in values:
                            if v is None or v in seen:
                                continue
                            seen.add(v)
                            uv.append(v)
                        values = uv
                aggvals.append(F.compute_aggregate(name, star, values, seps))
            fr = tuple(rep) + tuple(aggvals)
            if self.having is not None and truth(self.having(env + (fr,))) is not True:
                continue
            frames.append(fr)
        return frames


class SelectPlan:
    def __init__(self):
        self.cores: list = []
        self.ops: list = []
        self.order_specs: list = []
        self.order_cols: list = []       # compound: column indexes
        self.limit = None
        self.offset = None
        self.names: list = []
        self.affs: list = []

    @property
    def correlated(self) -> bool:
        return any(c.scope.correlated for c in self.cores)

    def run(self, env=()):
        if len(self.cores) == 1:
            pairs = self.cores[0].produce(env, bool(self.order_specs))
            if self.order_specs:
                cmp = _sort_cmp(self.order_specs)
                pairs.sort(key=functools.cmp_to_key(lambda x, y: cmp(x[1], y[1])))
            rows = [p[0] for p in pairs]
        else:
            rows = [p[0] for p in self.cores[0].produce(env, False)]
            for op, core in zip(self.ops, self.cores[1:]):
                right = [p[0] for p in core.produce(env, False)]
                if op == "UNION ALL":
                    rows = rows + right
                elif op == "UNION":
                    rows = _dedupe(rows + right)
                elif op == "INTERSECT":
                    rs = set(right)
                    rows = _dedupe([r for r in rows if r in rs])
                else:
                    rs = set(right)
                    rows = _dedupe([r for r in rows if r not in rs])
            if self.order_specs:
                cmp = _sort_cmp(self.order_specs)
                cols = self.order_cols
                rows.sort(key=functools.cmp_to_key(
                    lambda x, y: cmp(tuple(x[i] for i in cols), tuple(y[i] for i in cols))))
        if self.limit is not None or self.offset is not None:
            off = 0
            if self.offset is not None:
                off = max(0, _limit_value(self.offset(())))
            lim = -1
            if self.limit is not None:
                lim = _limit_value(self.limit(()))
            rows = rows[off:] if lim < 0 else rows[off:off + lim]
        return rows


# ====================================================================== compiler
class Compiler:
    def __init__(self, db: "Database", params: tuple, sql: str):
        self.db = db
        self.params = params
        self.sql = sql

    # ------------------------------------------------------------ select
    def select(self, sel: P.Select, parent: Scope | None) -> SelectPlan:
        plan = SelectPlan()
        single = len(sel.cores) == 1
        for core in sel.cores:
            plan.cores.append(self.core(core, parent, sel.order_by if single else None))
        n = len(plan.cores[0].names)
        for i, c in enumerate(plan.cores[1:]):
            if len(c.names) != n:
                raise Error(f"SELECTs to the left and right of {sel.ops[i]} do not have the same number of result columns")
        plan.ops = list(sel.ops)
        plan.names = plan.cores[0].names
        plan.affs = plan.cores[0].affs
        plan.order_specs = [(t.desc, t.nulls) for t in sel.order_by]
        if not single:
            first = plan.cores[0]
            for i, t in enumerate(sel.order_by):
                k = _int_literal(t.expr)
                if k is not None:
                    if not 1 <= k <= n:
                        raise Error(f"{_ordinal(i + 1)} ORDER BY term out of range - should be between 1 and {n}")
                    plan.order_cols.append(k - 1)
                    continue
                idx = None
                if isinstance(t.expr, P.ColumnRef) and t.expr.table is None:
                    for j, nm in enumerate(first.names):
                        if nm.lower() == t.expr.name.lower():
                            idx = j
                            break
                if idx is None:
                    raise Error(f"{_ordinal(i + 1)} ORDER BY term does not match any column in the result set")
                plan.order_cols.append(idx)
        empty = Scope([], None)
        if sel.limit is not None:
            plan.limit, _ = self.expr(sel.limit, empty)
        if sel.offset is not None:
            plan.offset, _ = self.expr(sel.offset, empty)
        return plan

    def core(self, core: P.SelectCore, parent: Scope | None, order_by) -> CorePlan:
        cp = CorePlan()
        sources = []
        steps = []
        offset = 0
        if core.from_:
            cp.has_from = True
            for item in core.from_:
                src_obj = item.source
                if isinstance(src_obj, P.TableSource):
                    t = self.db.get_table(src_obj.name)
                    cols = list(t.columns)
                    affs = list(t.affs)
                    name = src_obj.alias or t.name

                    def rows_fn(env, t=t):
                        return [tuple(r) for r in t.rows]
                else:
                    sub = self.select(src_obj.select, None)
                    cols = list(sub.names)
                    affs = list(sub.affs)
                    name = src_obj.alias or ""
                    cache: list = []

                    def rows_fn(env, sub=sub, cache=cache):
                        if not cache:
                            cache.append(sub.run(()))
                        return cache[0]
                src = Source(name, cols, affs, offset)
                steps.append({"kind": item.kind, "rows": rows_fn, "cond": None, "width": len(cols),
                              "item": item, "src": src})
                sources.append(src)
                offset += len(cols)
        scope = Scope(sources, parent)
        cp.scope = scope
        cp.width = scope.width
        # join conditions
        for i, step in enumerate(steps):
            item = step["item"]
            src = step["src"]
            if item.using:
                conds = []
                for col in item.using:
                    left = None
                    for lsrc in sources[:i]:
                        for j, c in enumerate(lsrc.columns):
                            if c.lower() == col.lower() and j not in lsrc.hidden:
                                left = (lsrc.offset + j, lsrc.affs[j])
                                break
                        if left:
                            break
                    right = None
                    for j, c in enumerate(src.columns):
                        if c.lower() == col.lower():
                            right = (src.offset + j, src.affs[j], j)
                            break
                    if left is None or right is None:
                        raise Error(f"cannot join using column {col} - column not present in both tables")
                    src.hidden.add(right[2])
                    conds.append((left[0], right[0], comparison_affinity(left[1], right[1])))

                def using_cond(env, conds=conds):
                    fr = env[-1]
                    for li, ri, aff in conds:
                        if _compare_op("=", fr[li], fr[ri], aff) != 1:
                            return 0
                    return 1
                step["cond"] = using_cond
            elif item.on is not None:
                scope.agg_clause = "ON"
                fn, _ = self.expr(item.on, scope)
                step["cond"] = fn
        cp.from_steps = steps

        # result columns (aliases are syntactic)
        scope.aliases = [(rc.alias, rc.expr) for rc in core.columns if rc.alias is not None and rc.expr is not None]
        cp.is_agg = bool(core.group_by) or any(_walk_aggs(rc.expr) for rc in core.columns)
        if core.having is not None and not cp.is_agg:
            raise Error("HAVING clause on a non-aggregate query")
        if cp.is_agg:
            cp.agg = AggCollector(scope.width)

        # WHERE
        if core.where is not None:
            scope.alias_active = True
            scope.agg_active = None
            scope.agg_clause = "WHERE"
            cp.where, _ = self.expr(core.where, scope)
            scope.alias_active = False

        # SELECT list
        scope.agg_active = cp.agg
        result_exprs = []   # Expr or ('col', index)
        alias_pos: dict = {}
        for rc in core.columns:
            if rc.star:
                if not sources:
                    raise Error("no tables specified")
                if rc.star_table is not None:
                    match = [s for s in sources if s.name.lower() == rc.star_table.lower()]
                    if not match:
                        raise Error(f"no such table: {rc.star_table}")
                    srcs = match[:1]
                    use_hidden = True
                else:
                    srcs = sources
                    use_hidden = False
                for s in srcs:
                    for j, c in enumerate(s.columns):
                        if not use_hidden and j in s.hidden:
                            continue
                        idx = s.offset + j
                        cp.outs.append(lambda env, idx=idx: env[-1][idx])
                        cp.names.append(c)
                        cp.affs.append(s.affs[j])
                        result_exprs.append(("col", idx))
                continue
            fn, aff = self.expr(rc.expr, scope)
            cp.outs.append(fn)
            cp.affs.append(aff)
            if rc.alias is not None:
                alias_pos.setdefault(rc.alias.lower(), len(cp.names))
                cp.names.append(rc.alias)
            elif isinstance(rc.expr, P.ColumnRef):
                cp.names.append(getattr(rc.expr, "resolved_name", rc.expr.name))
            else:
                cp.names.append(self.sql[rc.expr.span[0]:rc.expr.span[1]])
            result_exprs.append(rc.expr)

        # GROUP BY
        if core.group_by:
            scope.agg_active = None
            scope.agg_clause = "GROUP BY"
            scope.alias_active = True
            groups = []
            for i, g in enumerate(core.group_by):
                k = _int_literal(g)
                if k is not None:
                    if not 1 <= k <= len(result_exprs):
                        raise Error(f"{_ordinal(i + 1)} GROUP BY term out of range - should be between 1 and {len(result_exprs)}")
                    target = result_exprs[k - 1]
                    if isinstance(target, tuple):
                        idx = target[1]
                        groups.append(lambda env, idx=idx: env[-1][idx])
                        continue
                    if _walk_aggs(target):
                        raise Error("aggregate functions are not allowed in the GROUP BY clause")
                    fn, _ = self.expr(target, scope)
                else:
                    fn, _ = self.expr(g, scope)
                groups.append(fn)
            cp.group = groups
            scope.alias_active = False

        # HAVING
        if core.having is not None:
            scope.agg_active = cp.agg
            scope.agg_clause = "HAVING"
            scope.alias_active = True
            cp.having, _ = self.expr(core.having, scope)
            scope.alias_active = False

        # ORDER BY (single SELECT only)
        if order_by:
            scope.agg_active = cp.agg
            scope.agg_clause = "ORDER BY"
            n = len(cp.names)
            for i, t in enumerate(order_by):
                e = t.expr
                if isinstance(e, P.ColumnRef) and e.table is None and e.name.lower() in alias_pos:
                    cp.order_keys.append(("col", alias_pos[e.name.lower()]))
                    continue
                k = _int_literal(e)
                if k is not None:
                    if not 1 <= k <= n:
                        raise Error(f"{_ordinal(i + 1)} ORDER BY term out of range - should be between 1 and {n}")
                    cp.order_keys.append(("col", k - 1))
                    continue
                scope.alias_active = True
                fn, _ = self.expr(e, scope)
                scope.alias_active = False
                cp.order_keys.append(("fn", fn))
        scope.agg_active = None
        cp.distinct = core.distinct
        return cp

    # ------------------------------------------------------------ expressions
    def expr(self, e, scope: Scope):
        """Compile expression -> (fn(env) -> value, affinity)."""
        if isinstance(e, P.Literal):
            v = e.value
            return (lambda env: v), None
        if isinstance(e, P.Param):
            v = self.params[e.index]
            return (lambda env: v), None
        if isinstance(e, P.ColumnRef):
            return self.column(e, scope)
        if isinstance(e, P.Unary):
            f, aff = self.expr(e.operand, scope)
            if e.op == "-":
                return (lambda env: _negate(f(env))), None
            if e.op == "+":
                return f, None
            return (lambda env: sql_bool(_not(truth(f(env))))), None
        if isinstance(e, P.Binary):
            return self.binary(e, scope)
        if isinstance(e, P.Between):
            xf, xa = self.expr(e.expr, scope)
            lf, la = self.expr(e.low, scope)
            hf, ha = self.expr(e.high, scope)
            a1 = comparison_affinity(xa, la)
            a2 = comparison_affinity(xa, ha)
            neg = e.negated

            def between(env):
                x = xf(env)
                r = _and(_tb(_compare_op(">=", x, lf(env), a1)), _tb(_compare_op("<=", x, hf(env), a2)))
                if neg:
                    return None if r is None else 1 - r
                return r
            return between, None
        if isinstance(e, P.InList):
            xf, xa = self.expr(e.expr, scope)
            items = [self.expr(i, scope)[0] for i in e.items]
            aff = comparison_affinity(xa, None)
            neg = e.negated

            def in_list(env):
                if not items:
                    return 1 if neg else 0
                x = xf(env)
                if x is None:
                    return None
                x = apply_cmp_affinity(x, aff)
                has_null = False
                for it in items:
                    v = it(env)
                    if v is None:
                        has_null = True
                        continue
                    if compare(x, apply_cmp_affinity(v, aff)) == 0:
                        return 0 if neg else 1
                if has_null:
                    return None
                return 1 if neg else 0
            return in_list, None
        if isinstance(e, P.InSelect):
            xf, xa = self.expr(e.expr, scope)
            plan = self.select(e.select, scope)
            if len(plan.names) != 1:
                raise Error(f"sub-select returns {len(plan.names)} columns - expected 1")
            aff = comparison_affinity(xa, plan.affs[0])
            rows_of = self._subquery_runner(plan)
            neg = e.negated

            def in_select(env):
                rows = rows_of(env)
                if not rows:
                    return 1 if neg else 0
                x = xf(env)
                if x is None:
                    return None
                x = apply_cmp_affinity(x, aff)
                has_null = False
                for (v,) in rows:
                    if v is None:
                        has_null = True
                        continue
                    if compare(x, apply_cmp_affinity(v, aff)) == 0:
                        return 0 if neg else 1
                if has_null:
                    return None
                return 1 if neg else 0
            return in_select, None
        if isinstance(e, P.Exists):
            plan = self.select(e.select, scope)
            rows_of = self._subquery_runner(plan)
            return (lambda env: 1 if rows_of(env) else 0), None
        if isinstance(e, P.Subquery):
            plan = self.select(e.select, scope)
            if len(plan.names) != 1:
                raise Error(f"sub-select returns {len(plan.names)} columns - expected 1")
            rows_of = self._subquery_runner(plan)

            def scalar(env):
                rows = rows_of(env)
                return rows[0][0] if rows else None
            return scalar, plan.affs[0]
        if isinstance(e, P.Like):
            sf, _ = self.expr(e.expr, scope)
            pf, _ = self.expr(e.pattern, scope)
            ef = self.expr(e.escape, scope)[0] if e.escape is not None else None
            neg = e.negated

            def like(env):
                s = sf(env)
                p = pf(env)
                esc = None
                if ef is not None:
                    ev = ef(env)
                    if ev is None:
                        return None
                    esc = to_text(ev)
                    if len(esc) != 1:
                        raise Error("ESCAPE expression must be a single character")
                if s is None or p is None:
                    return None
                m = _like_regex(to_text(p), esc).fullmatch(to_text(s)) is not None
                return 1 if m != neg else 0
            return like, None
        if isinstance(e, P.Case):
            return self.case(e, scope)
        if isinstance(e, P.Cast):
            f, _ = self.expr(e.expr, scope)
            aff = type_affinity(e.type_name)
            return (lambda env: _cast(f(env), aff)), aff
        if isinstance(e, P.FuncCall):
            return self.func(e, scope)
        raise Error("unsupported expression")

    def _subquery_runner(self, plan: SelectPlan):
        if plan.correlated:
            return plan.run
        cache: list = []

        def run(env):
            if not cache:
                cache.append(plan.run(env))
            return cache[0]
        return run

    def column(self, ref: P.ColumnRef, scope: Scope):
        level = 0
        s = scope
        while s is not None:
            hits = s.lookup(ref.table, ref.name)
            if len(hits) > 1:
                shown = f"{ref.table}.{ref.name}" if ref.table else ref.name
                raise Error(f"ambiguous column name: {shown}")
            if hits:
                idx, aff, declared = hits[0]
                ref.resolved_name = declared
                t = scope
                for _ in range(level):
                    t.correlated = True
                    t = t.parent
                if level == 0:
                    return (lambda env: env[-1][idx]), aff
                lv = level + 1
                return (lambda env: env[-lv][idx]), aff
            if ref.table is None and s.alias_active:
                for aname, aexpr in s.aliases:
                    if aname.lower() == ref.name.lower():
                        if s.agg_active is None and _walk_aggs(aexpr):
                            raise Error(f"misuse of aliased aggregate {aname}")
                        s.alias_active = False
                        try:
                            f, aff = self.expr(aexpr, s)
                        finally:
                            s.alias_active = True
                        t = scope
                        for _ in range(level):
                            t.correlated = True
                            t = t.parent
                        if level == 0:
                            return f, aff
                        cut = level

                        def outer_alias(env, f=f, cut=cut):
                            return f(env[:len(env) - cut])
                        return outer_alias, aff
            s = s.parent
            level += 1
        shown = f"{ref.table}.{ref.name}" if ref.table else ref.name
        raise Error(f"no such column: {shown}")

    def binary(self, e: P.Binary, scope: Scope):
        lf, la = self.expr(e.left, scope)
        rf, ra = self.expr(e.right, scope)
        op = e.op
        if op in ("+", "-", "*", "/", "%"):
            return (lambda env: _arith(op, lf(env), rf(env))), None
        if op == "||":
            return (lambda env: _concat(lf(env), rf(env))), None
        if op == "AND":
            def and_(env):
                a = truth(lf(env))
                if a is False:
                    return 0
                b = truth(rf(env))
                if b is False:
                    return 0
                if a is None or b is None:
                    return None
                return 1
            return and_, None
        if op == "OR":
            def or_(env):
                a = truth(lf(env))
                if a is True:
                    return 1
                b = truth(rf(env))
                if b is True:
                    return 1
                if a is None or b is None:
                    return None
                return 0
            return or_, None
        aff = comparison_affinity(la, ra)
        if op in ("IS", "ISNOT"):
            want = 1 if op == "IS" else 0

            def is_(env):
                a = lf(env)
                b = rf(env)
                if a is None or b is None:
                    same = a is None and b is None
                else:
                    same = compare(apply_cmp_affinity(a, aff), apply_cmp_affinity(b, aff)) == 0
                return want if same else 1 - want
            return is_, None
        return (lambda env: _compare_op(op, lf(env), rf(env), aff)), None

    def case(self, e: P.Case, scope: Scope):
        whens = []
        if e.base is not None:
            bf, ba = self.expr(e.base, scope)
            for w, t in e.whens:
                wf, wa = self.expr(w, scope)
                tf, _ = self.expr(t, scope)
                whens.append((wf, comparison_affinity(ba, wa), tf))
        else:
            bf = None
            for w, t in e.whens:
                wf, _ = self.expr(w, scope)
                tf, _ = self.expr(t, scope)
                whens.append((wf, None, tf))
        ef = self.expr(e.else_, scope)[0] if e.else_ is not None else None

        def case(env):
            if bf is not None:
                b = bf(env)
                for wf, aff, tf in whens:
                    if _compare_op("=", b, wf(env), aff) == 1:
                        return tf(env)
            else:
                for wf, _, tf in whens:
                    if truth(wf(env)) is True:
                        return tf(env)
            return ef(env) if ef is not None else None
        return case, None

    def func(self, e: P.FuncCall, scope: Scope):
        name = e.name
        nargs = len(e.args)
        if F.is_aggregate_call(name, nargs, e.star):
            F.check_aggregate(name, nargs, e.star, e.distinct)
            coll = scope.agg_active
            if coll is None:
                raise Error(f"misuse of aggregate function {name}()")
            scope.agg_active = None
            try:
                arg_fn = self.expr(e.args[0], scope)[0] if nargs >= 1 else None
                sep_fn = self.expr(e.args[1], scope)[0] if nargs >= 2 else None
            finally:
                scope.agg_active = coll
            star = e.star or (name == "count" and nargs == 0)
            idx = coll.add((name, star, e.distinct, arg_fn, sep_fn))
            return (lambda env: env[-1][idx]), None
        F.check_scalar(name, nargs)
        if e.distinct:
            raise Error(f"DISTINCT aggregates must have exactly one argument")
        fn = F.SCALARS[name][0]
        argfs = [self.expr(a, scope)[0] for a in e.args]
        if len(argfs) == 1:
            a0 = argfs[0]
            return (lambda env: fn(a0(env))), None
        return (lambda env: fn(*[a(env) for a in argfs])), None


def _not(b):
    if b is None:
        return None
    return not b


def _tb(v):
    """SQL int/NULL -> True/False/None."""
    if v is None:
        return None
    return v != 0


# ====================================================================== database
class Database:
    def __init__(self):
        self.tables: dict = {}

    def get_table(self, name: str) -> Table:
        t = self.tables.get(name.lower())
        if t is None:
            raise Error(f"no such table: {name}")
        return t

    def execute(self, stmt, params: tuple, sql: str):
        """Returns (rows, names or None, rowcount)."""
        comp = Compiler(self, params, sql)
        if isinstance(stmt, P.Select):
            plan = comp.select(stmt, None)
            rows = plan.run(())
            return rows, list(plan.names), -1
        if isinstance(stmt, P.CreateTable):
            return self.create(stmt)
        if isinstance(stmt, P.Insert):
            return self.insert(stmt, comp)
        if isinstance(stmt, P.Update):
            return self.update(stmt, comp)
        if isinstance(stmt, P.Delete):
            return self.delete(stmt, comp)
        raise Error("unsupported statement")

    def create(self, stmt: P.CreateTable):
        if stmt.name.lower() in self.tables:
            raise Error(f"table {stmt.name} already exists")
        names = []
        affs = []
        seen = set()
        for cname, tname in stmt.columns:
            if cname.lower() in seen:
                raise Error(f"duplicate column name: {cname}")
            seen.add(cname.lower())
            names.append(cname)
            affs.append(type_affinity(tname))
        self.tables[stmt.name.lower()] = Table(stmt.name, names, affs)
        return [], None, -1

    def _target_columns(self, t: Table, cols):
        if cols is None:
            return list(range(len(t.columns)))
        idxs = []
        for c in cols:
            for j, tc in enumerate(t.columns):
                if tc.lower() == c.lower():
                    idxs.append(j)
                    break
            else:
                raise Error(f"table {t.name} has no column named {c}")
        return idxs

    def insert(self, stmt: P.Insert, comp: Compiler):
        t = self.get_table(stmt.table)
        idxs = self._target_columns(t, stmt.columns)
        if stmt.rows is not None:
            width = len(stmt.rows[0])
            if any(len(r) != width for r in stmt.rows):
                raise Error("all VALUES must have the same number of terms")
            if width != len(idxs):
                if stmt.columns is None:
                    raise Error(f"table {t.name} has {len(idxs)} columns but {width} values were supplied")
                raise Error(f"{width} values for {len(idxs)} columns")
            empty = Scope([], None)
            fns = [[comp.expr(e, empty)[0] for e in r] for r in stmt.rows]
            values = [[f(((),)) for f in r] for r in fns]
        else:
            plan = comp.select(stmt.select, None)
            width = len(plan.names)
            if width != len(idxs):
                if stmt.columns is None:
                    raise Error(f"table {t.name} has {len(idxs)} columns but {width} values were supplied")
                raise Error(f"{width} values for {len(idxs)} columns")
            values = [list(r) for r in plan.run(())]
        new_rows = []
        for vals in values:
            row = [None] * len(t.columns)
            for j, v in zip(idxs, vals):
                row[j] = apply_storage_affinity(v, t.affs[j])
            new_rows.append(row)
        t.rows.extend(new_rows)
        return [], None, len(new_rows)

    def _table_scope(self, t: Table) -> Scope:
        return Scope([Source(t.name, list(t.columns), list(t.affs), 0)], None)

    def update(self, stmt: P.Update, comp: Compiler):
        t = self.get_table(stmt.table)
        scope = self._table_scope(t)
        sets = []
        for col, e in stmt.sets:
            for j, tc in enumerate(t.columns):
                if tc.lower() == col.lower():
                    break
            else:
                raise Error(f"no such column: {col}")
            f, _ = comp.expr(e, scope)
            sets.append((j, f))
        where = comp.expr(stmt.where, scope)[0] if stmt.where is not None else None
        matched = [i for i, r in enumerate(t.rows) if where is None or truth(where((tuple(r),))) is True]
        updates = []
        for i in matched:
            old = tuple(t.rows[i])
            new = list(old)
            env = (old,)
            for j, f in sets:
                new[j] = apply_storage_affinity(f(env), t.affs[j])
            updates.append((i, new))
        for i, new in updates:
            t.rows[i] = new
        return [], None, len(matched)

    def delete(self, stmt: P.Delete, comp: Compiler):
        t = self.get_table(stmt.table)
        scope = self._table_scope(t)
        where = comp.expr(stmt.where, scope)[0] if stmt.where is not None else None
        keep = []
        n = 0
        for r in t.rows:
            if where is None or truth(where((tuple(r),))) is True:
                n += 1
            else:
                keep.append(r)
        t.rows[:] = keep
        return [], None, n
