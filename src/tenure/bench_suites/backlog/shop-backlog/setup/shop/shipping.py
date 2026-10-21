"""배송비 규칙.

지역별 기본 요금과, 2kg 를 넘는 무게에 대해 '시작된 1kg 마다' 붙는 할증이 있다.

| 지역 | 기본 | 1kg 마다 |
|---|---|---|
| domestic | 4.90 | 1.00 |
| eu | 9.90 | 2.50 |
| world | 19.90 | 5.00 |

- 국내(domestic)는 상품 금액이 50.00 이상이면 무료. 이때 상품 금액은 수량 할인 뒤, **쿠폰 할인 전** 소계다.
- free_shipping 쿠폰이 있으면 지역과 상관없이 0.
- 무게는 줄마다 (단위 무게 x 수량) 의 합.
"""

from __future__ import annotations

from decimal import Decimal

from .errors import ValidationError
from .money import ZERO

REGIONS: dict[str, tuple[Decimal, Decimal]] = {
    "domestic": (Decimal("4.90"), Decimal("1.00")),
    "eu": (Decimal("9.90"), Decimal("2.50")),
    "world": (Decimal("19.90"), Decimal("5.00")),
}
FREE_THRESHOLD = Decimal("50.00")
BASE_WEIGHT_G = 2000


def check_region(region: str) -> str:
    if region not in REGIONS:
        raise ValidationError(f"모르는 배송 지역: {region} (가능: {', '.join(REGIONS)})")
    return region


def shipping_cost(region: str, weight_g: int, merchandise: Decimal) -> Decimal:
    """배송비(세금 제외). merchandise 는 쿠폰 할인 전 상품 소계."""
    base, per_kg = REGIONS[check_region(region)]
    if region == "domestic" and merchandise >= FREE_THRESHOLD:
        return ZERO
    extra = max(0, weight_g - BASE_WEIGHT_G)
    kgs = -(-extra // 1000)
    return base + per_kg * kgs
