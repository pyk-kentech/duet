"""부가가치세(VAT).

- 세율은 카테고리별이다. 표에 없는 카테고리는 기본 세율(19%)을 쓴다. 기본 표: books 7%, food 7%.
- 세금은 주문 줄마다 '쿠폰 할인 뒤 금액'에 세율을 곱해 센트로 반올림한다(줄마다 반올림).
- 배송비에는 기본 세율을 매긴다.
- 표시 모드(settings.tax_display): exclusive 면 금액을 세금 제외로, inclusive 면 show·quote 의
  줄 단가·줄 금액을 세금 포함으로 보여 준다. 계산된 세금·합계는 표시 모드와 상관없다.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .catalog import check_category
from .money import HUNDRED, parse_percent, round_money

DEFAULT_RATE = Decimal("19")
DEFAULT_RATES = {"books": Decimal("7"), "food": Decimal("7")}


class TaxTable:
    def __init__(self, rates: dict[str, Decimal] | None = None, default: Decimal = DEFAULT_RATE) -> None:
        self.default = default
        self.rates: dict[str, Decimal] = dict(DEFAULT_RATES if rates is None else rates)

    def rate_for(self, category: str) -> Decimal:
        return self.rates.get(category, self.default)

    def set_rate(self, category: str, rate: object) -> None:
        self.rates[check_category(category)] = parse_percent(rate)

    def items(self) -> list[tuple[str, Decimal]]:
        """표에 있는 (카테고리, 세율), 카테고리 순. 기본 세율은 포함하지 않는다."""
        return sorted(self.rates.items())

    @property
    def shipping_rate(self) -> Decimal:
        return self.default


def line_tax(net: Decimal, rate: Decimal) -> Decimal:
    """줄 하나의 세금. (모듈이 생기기 전 코드에서 옮겨 와 quantize 를 직접 쓴다)"""
    return (net * rate / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def gross(net: Decimal, rate: Decimal) -> Decimal:
    """세금 포함 표시용 금액."""
    return round_money(net * (HUNDRED + rate) / HUNDRED)


def format_rate(rate: Decimal) -> str:
    """'7', '19', '7.5' — 보고서에 쓰는 세율 표기 (뒤의 0 없음)."""
    text = format(rate.normalize(), "f")
    return text
