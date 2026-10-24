"""Values, affinities, conversions and comparisons (SQLite rules).

Values are Python None (NULL), int (INTEGER), float (REAL) and str (TEXT).
Affinity of an expression: one of INTEGER, REAL, NUMERIC, TEXT, BLOB, or None (no affinity).
"""

from __future__ import annotations

import math
import re

INTEGER, REAL, NUMERIC, TEXT, BLOB = "INTEGER", "REAL", "NUMERIC", "TEXT", "BLOB"
NUMERIC_AFFS = (INTEGER, REAL, NUMERIC)

_WS = " \t\n\r\f\v"
_FULL_NUM = re.compile(r"[ \t\n\r\f\v]*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)[ \t\n\r\f\v]*\Z")
_PREFIX_NUM = re.compile(r"[ \t\n\r\f\v]*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)")
_PREFIX_INT = re.compile(r"[ \t\n\r\f\v]*([+-]?\d+)")

I64_MIN, I64_MAX = -2**63, 2**63 - 1


def type_affinity(type_name: str | None) -> str:
    """Affinity from a declared type name (SQLite's five rules, in order)."""
    if not type_name:
        return BLOB
    t = type_name.upper()
    if "INT" in t:
        return INTEGER
    if "CHAR" in t or "CLOB" in t or "TEXT" in t:
        return TEXT
    if "BLOB" in t:
        return BLOB
    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return REAL
    return NUMERIC


def _num_from_literal(text: str) -> int | float:
    if "." in text or "e" in text or "E" in text:
        return float(text)
    v = int(text)
    if I64_MIN <= v <= I64_MAX:
        return v
    return float(text)


def full_numeric(s: str) -> int | float | None:
    """The number if the whole text (surrounding spaces allowed) is a numeric literal, else None."""
    m = _FULL_NUM.match(s)
    if not m:
        return None
    return _num_from_literal(m.group(1))


def prefix_numeric(s: str) -> int | float:
    """Longest numeric prefix (after leading spaces). '.'/exponent -> REAL, else INTEGER, none -> 0."""
    m = _PREFIX_NUM.match(s)
    if not m:
        return 0
    return _num_from_literal(m.group(1))


def real_to_int_if_exact(f: float) -> int | float:
    if f == f and not math.isinf(f) and f == math.floor(f) and I64_MIN < f < I64_MAX:
        return int(f)
    return f


def fmt_real(x: float) -> str:
    if x != x:
        return "NaN"  # not reachable through tested features
    if math.isinf(x):
        return "Inf" if x > 0 else "-Inf"
    if x == 0:
        return "0.0"
    s = "%.15g" % x
    if "e" in s:
        mant, exp = s.split("e")
        if "." not in mant:
            mant += ".0"
        return mant + "e" + exp
    if "." not in s:
        s += ".0"
    return s


def to_text(v):
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, int):
        return str(v)
    return fmt_real(v)


def to_number(v):
    """Numeric value used by arithmetic (text -> numeric prefix)."""
    if v is None or isinstance(v, (int, float)):
        return v
    return prefix_numeric(v)


def to_real(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, float):
        return v
    if isinstance(v, int):
        return float(v)
    return float(prefix_numeric(v))


def to_int(v) -> int:
    """Integer value of v: REAL truncated toward zero, TEXT -> integer prefix."""
    if v is None:
        return 0
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if v != v:
            return 0
        if v >= 9.223372036854775807e18:
            return I64_MAX
        if v <= -9.223372036854775808e18:
            return I64_MIN
        return int(v)
    m = _PREFIX_INT.match(v)
    if not m:
        return 0
    i = int(m.group(1))
    return max(I64_MIN, min(I64_MAX, i))


def truth(v):
    """True / False / None (unknown)."""
    if v is None:
        return None
    if isinstance(v, int):
        return v != 0
    if isinstance(v, float):
        return v != 0.0
    return to_real(v) != 0.0


def sql_bool(b):
    if b is None:
        return None
    return 1 if b else 0


# ---------------------------------------------------------------- storage affinity
def apply_storage_affinity(v, aff: str):
    if v is None:
        return None
    if aff in (INTEGER, NUMERIC):
        if isinstance(v, str):
            n = full_numeric(v)
            if n is None:
                return v
            if isinstance(n, float):
                return real_to_int_if_exact(n)
            return n
        if isinstance(v, float):
            return real_to_int_if_exact(v)
        return v
    if aff == REAL:
        if isinstance(v, str):
            n = full_numeric(v)
            if n is None:
                return v
            return float(n)
        if isinstance(v, int):
            return float(v)
        return v
    if aff == TEXT:
        if isinstance(v, (int, float)):
            return to_text(v)
        return v
    return v


# ---------------------------------------------------------------- comparison
def comparison_affinity(a1, a2):
    """Conversion to apply before comparing two operands with affinities a1, a2."""
    if a1 is not None and a2 is not None:
        if a1 in NUMERIC_AFFS or a2 in NUMERIC_AFFS:
            return NUMERIC
        return None
    a = a1 if a1 is not None else a2
    if a is None:
        return None
    if a in NUMERIC_AFFS:
        return NUMERIC
    if a == TEXT:
        return TEXT
    return None


def apply_cmp_affinity(v, aff):
    if aff is None or v is None:
        return v
    if aff == NUMERIC:
        if isinstance(v, str):
            n = full_numeric(v)
            return v if n is None else n
        return v
    if aff == TEXT:
        if isinstance(v, (int, float)):
            return to_text(v)
    return v


def _rank(v) -> int:
    if v is None:
        return 0
    if isinstance(v, str):
        return 2
    return 1


def compare(a, b) -> int:
    """Total order used for comparison and sorting: NULL < numbers < text."""
    ra, rb = _rank(a), _rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    if ra == 0:
        return 0
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def typeof(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, str):
        return "text"
    if isinstance(v, int):
        return "integer"
    return "real"
