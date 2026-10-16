import re
from decimal import Decimal

PRECISION = {"JPY": 0, "KRW": 0}
_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_AMOUNT_RE = re.compile(rf"^(-?)({_NUM})$|^\(({_NUM})\)$")
_CUR_RE = re.compile(r"^[A-Z]{3}$")


def precision(currency: str) -> int:
    return PRECISION.get(currency, 2)


def parse_amount(text: str, currency: str) -> Decimal:
    """금액 문자열 → Decimal. 형식이 틀리거나 자릿수가 넘치면 ValueError."""
    if not _CUR_RE.match(currency):
        raise ValueError(f"통화 형식 오류: {currency!r}")
    m = _AMOUNT_RE.match(text)
    if not m:
        raise ValueError(f"금액 형식 오류: {text!r}")
    sign, num, paren = m.groups()
    raw = (num if num is not None else paren).replace(",", "")
    value = Decimal(raw)
    if "." in raw and len(raw.split(".")[1]) > precision(currency):
        raise ValueError(f"{currency} 는 소수 {precision(currency)}자리까지: {text}")
    return -value if (sign or paren is not None) else value


def fmt(value: Decimal, currency: str) -> str:
    p = precision(currency)
    return f"{value:,.{p}f}"
