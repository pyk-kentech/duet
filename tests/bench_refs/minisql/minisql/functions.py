"""Scalar functions and aggregate accumulators."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .errors import Error
from .values import compare, to_int, to_real, to_text, typeof

_ASCII_UPPER = {ord(c): ord(c) - 32 for c in "abcdefghijklmnopqrstuvwxyz"}
_ASCII_LOWER = {ord(c) + 0: ord(c) + 32 for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}


def f_abs(x):
    if x is None:
        return None
    if isinstance(x, int):
        return abs(x)
    if isinstance(x, float):
        return abs(x)
    return abs(to_real(x))


def f_length(x):
    if x is None:
        return None
    return len(to_text(x))


def f_upper(x):
    if x is None:
        return None
    return to_text(x).translate(_ASCII_UPPER)


def f_lower(x):
    if x is None:
        return None
    return to_text(x).translate(_ASCII_LOWER)


def f_substr(x, y, z=Ellipsis):
    if x is None or y is None or z is None:
        return None
    s = to_text(x)
    n = len(s)
    p1 = to_int(y)
    neg = False
    if z is Ellipsis:
        p2 = 1 << 62
    else:
        p2 = to_int(z)
        if p2 < 0:
            p2 = -p2
            neg = True
    if p1 < 0:
        p1 += n
        if p1 < 0:
            p2 += p1
            if p2 < 0:
                p2 = 0
            p1 = 0
    elif p1 > 0:
        p1 -= 1
    elif p2 > 0:
        p2 -= 1
    if neg:
        p1 -= p2
        if p1 < 0:
            p2 += p1
            p1 = 0
    return s[p1:p1 + p2]


def _trim(mode):
    def fn(x, y=Ellipsis):
        if x is None or y is None:
            return None
        s = to_text(x)
        chars = " " if y is Ellipsis else to_text(y)
        if mode == "both":
            return s.strip(chars) if chars else s
        if mode == "left":
            return s.lstrip(chars) if chars else s
        return s.rstrip(chars) if chars else s
    return fn


def f_replace(x, y, z):
    if x is None or y is None:
        return None
    pat = to_text(y)
    if pat == "":
        return x          # unchanged, original type
    if z is None:
        return None
    return to_text(x).replace(pat, to_text(z))


def f_instr(x, y):
    if x is None or y is None:
        return None
    return to_text(x).find(to_text(y)) + 1


def f_round(x, n=Ellipsis):
    if x is None or n is None:
        return None
    digits = 0 if n is Ellipsis else to_int(n)
    digits = max(0, min(30, digits))
    r = to_real(x)
    if r != r or r < -4503599627370496.0 or r > 4503599627370496.0:
        return r
    if digits == 0:
        return float(int(r + (-0.5 if r < 0 else 0.5)))
    q = Decimal(repr(r)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return float(q)


def f_coalesce(*args):
    for a in args:
        if a is not None:
            return a
    return None


def f_nullif(x, y):
    if x is None:
        return None
    if y is not None and compare(x, y) == 0:
        return None
    return x


def f_typeof(x):
    return typeof(x)


def f_max(*args):
    best = 0
    if args[0] is None:
        return None
    for i in range(1, len(args)):
        if args[i] is None:
            return None
        if compare(args[best], args[i]) < 0:
            best = i
    return args[best]


def f_min(*args):
    best = 0
    if args[0] is None:
        return None
    for i in range(1, len(args)):
        if args[i] is None:
            return None
        if compare(args[best], args[i]) >= 0:
            best = i
    return args[best]


# name -> (function, min args, max args or None for unlimited)
SCALARS = {
    "abs": (f_abs, 1, 1),
    "length": (f_length, 1, 1),
    "upper": (f_upper, 1, 1),
    "lower": (f_lower, 1, 1),
    "substr": (f_substr, 2, 3),
    "trim": (_trim("both"), 1, 2),
    "ltrim": (_trim("left"), 1, 2),
    "rtrim": (_trim("right"), 1, 2),
    "replace": (f_replace, 3, 3),
    "instr": (f_instr, 2, 2),
    "round": (f_round, 1, 2),
    "coalesce": (f_coalesce, 2, None),
    "ifnull": (f_coalesce, 2, 2),
    "nullif": (f_nullif, 2, 2),
    "typeof": (f_typeof, 1, 1),
    "max": (f_max, 2, None),
    "min": (f_min, 2, None),
}

# aggregate name -> (min args, max args)
AGG_ARGS = {
    "count": (0, 1),
    "sum": (1, 1),
    "total": (1, 1),
    "avg": (1, 1),
    "min": (1, 1),
    "max": (1, 1),
    "group_concat": (1, 2),
}


def is_aggregate_call(name: str, nargs: int, star: bool) -> bool:
    if name in ("min", "max"):
        return nargs == 1
    return name in AGG_ARGS


def check_scalar(name: str, nargs: int):
    if name not in SCALARS:
        raise Error(f"no such function: {name}")
    _, lo, hi = SCALARS[name]
    if nargs < lo or (hi is not None and nargs > hi):
        raise Error(f"wrong number of arguments to function {name}()")


def check_aggregate(name: str, nargs: int, star: bool, distinct: bool):
    lo, hi = AGG_ARGS[name]
    if star:
        if name != "count":
            raise Error(f"wrong number of arguments to function {name}()")
        return
    if nargs < lo or nargs > hi:
        raise Error(f"wrong number of arguments to function {name}()")
    if distinct and nargs != 1:
        raise Error("DISTINCT aggregates must have exactly one argument")


def compute_aggregate(name: str, star: bool, values: list, seps: list | None):
    """values: argument values for the rows of a group (already DISTINCT-filtered if requested)."""
    if name == "count":
        if star:
            return len(values)
        return sum(1 for v in values if v is not None)
    vals = [v for v in values if v is not None]
    if name in ("sum", "total", "avg"):
        nums = []
        all_int = True
        for v in vals:
            if isinstance(v, str):
                from .values import full_numeric
                n = full_numeric(v)
                if isinstance(n, int):
                    v = n
                else:
                    v = to_real(v)
            if not isinstance(v, int):
                all_int = False
            nums.append(v)
        if name == "sum":
            if not nums:
                return None
            if all_int:
                return sum(nums)
            return _fsum(nums)
        if name == "total":
            return _fsum(nums) if nums else 0.0
        if not nums:
            return None
        return (sum(nums) if all_int else _fsum(nums)) / len(nums)
    if name in ("min", "max"):
        if not vals:
            return None
        best = vals[0]
        for v in vals[1:]:
            c = compare(v, best)
            if (name == "min" and c < 0) or (name == "max" and c > 0):
                best = v
        return best
    if name == "group_concat":
        out = None
        for i, v in enumerate(values):
            if v is None:
                continue
            t = to_text(v)
            if out is None:
                out = t
            else:
                sep = "," if seps is None else seps[i]
                out += ("" if sep is None else to_text(sep)) + t
        return out
    raise Error(f"no such function: {name}")


def _fsum(nums) -> float:
    import math
    return float(math.fsum(float(x) for x in nums))
