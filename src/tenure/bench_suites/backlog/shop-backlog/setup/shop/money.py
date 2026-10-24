"""금액 계산 도우미.

이 가게의 금액은 모두 EUR 이고 `Decimal` 로 다룬다. 저장·표시는 센트(소수 둘째 자리) 단위,
반올림은 ROUND_HALF_UP (0.005 -> 0.01) 이다. 새 코드는 여기 있는 함수를 쓴다.
(오래된 모듈 몇 곳은 아직 `quantize(...)` 를 직접 부른다. 결과는 같다.)
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Iterable

from .errors import ValidationError

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
HUNDRED = Decimal("100")


def to_decimal(value: object) -> Decimal:
    """str/int/float/Decimal 을 Decimal 로. float 는 repr 을 거쳐 바꾼다(19.99 -> Decimal('19.99'))."""
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, bool):
        raise ValidationError(f"숫자가 아닙니다: {value!r}")
    elif isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, float):
        d = Decimal(repr(value))
    elif isinstance(value, str):
        try:
            d = Decimal(value.strip())
        except InvalidOperation:
            raise ValidationError(f"숫자가 아닙니다: {value!r}") from None
    else:
        raise ValidationError(f"숫자가 아닙니다: {value!r}")
    if not d.is_finite():
        raise ValidationError(f"숫자가 아닙니다: {value!r}")
    return d


def round_money(value: object) -> Decimal:
    """센트 단위로 반올림 (ROUND_HALF_UP)."""
    return to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def parse_money(value: object) -> Decimal:
    """사용자가 준 금액. 0 이상, 소수 둘째 자리까지. 값은 준 그대로 돌려준다('19.9' -> Decimal('19.9'))."""
    d = to_decimal(value)
    if d < 0:
        raise ValidationError(f"금액은 음수일 수 없습니다: {value}")
    if d != d.quantize(CENT):
        raise ValidationError(f"금액은 소수 둘째 자리까지입니다: {value}")
    return d


def parse_percent(value: object, *, allow_100: bool = True) -> Decimal:
    """할인율·세율 같은 백분율. 0 초과 100 이하 (allow_100=False 면 100 미만)."""
    d = to_decimal(value)
    if d <= 0 or d > HUNDRED or (d == HUNDRED and not allow_100):
        raise ValidationError(f"백분율 범위가 아닙니다: {value}")
    return d


def percent_of(amount: Decimal, pct: Decimal) -> Decimal:
    """amount 의 pct% 를 센트로 반올림."""
    return round_money(to_decimal(amount) * to_decimal(pct) / HUNDRED)


def fmt(value: object) -> str:
    """표시용 금액 문자열: 항상 소수 둘째 자리 ('12.30', '-5.00')."""
    return format(round_money(value), "f")


def total(values: Iterable[Decimal]) -> Decimal:
    s = ZERO
    for v in values:
        s += v
    return s


def allocate(amount: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """amount 를 weights 비율로 센트 단위로 나눈다.

    각 몫은 반올림하고, 반올림 때문에 남거나 모자란 센트는 weight 가 가장 큰 항목에 몰아준다
    (같으면 앞의 것). weights 합이 0 이면 모두 0.
    """
    s = total(weights)
    if s == 0 or amount == 0:
        return [ZERO for _ in weights]
    parts = [round_money(amount * w / s) for w in weights]
    diff = amount - total(parts)
    if diff:
        big = max(range(len(weights)), key=lambda k: (weights[k], -k))
        parts[big] += diff
    return parts
