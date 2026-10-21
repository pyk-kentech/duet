"""장바구니와 견적(quote).

견적은 주문하기 전에 고객에게 보여 주는 금액이다. 같은 상품·수량·지역·쿠폰이면 견적의 줄 금액과 합계는
그 조건으로 주문(checkout)했을 때와 **같아야 한다**. 견적은 재고를 확인하거나 예약하지 않고,
쿠폰 사용 횟수도 올리지 않는다.

(이 모듈은 pricing.price_lines 보다 먼저 만들어져 줄 단가를 직접 계산한다.)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .catalog import Catalog
from .errors import ValidationError
from .money import ZERO, total
from .pricing import Coupon, PricedLine, apply_coupons, check_coupons
from .shipping import check_region, shipping_cost
from .tax import TaxTable, line_tax


@dataclass
class QuoteLine:
    sku: str
    name: str
    category: str
    qty: int
    list_price: Decimal
    unit_price: Decimal
    discount: Decimal
    tax_rate: Decimal
    tax: Decimal

    @property
    def amount(self) -> Decimal:
        return self.unit_price * self.qty

    @property
    def net(self) -> Decimal:
        return self.amount - self.discount


@dataclass
class Quote:
    lines: list[QuoteLine]
    shipping: Decimal
    shipping_tax: Decimal

    @property
    def subtotal(self) -> Decimal:
        return total(line.amount for line in self.lines)

    @property
    def discount(self) -> Decimal:
        return total(line.discount for line in self.lines)

    @property
    def net(self) -> Decimal:
        return self.subtotal - self.discount

    @property
    def tax(self) -> Decimal:
        return total(line.tax for line in self.lines) + self.shipping_tax

    @property
    def total(self) -> Decimal:
        return self.net + self.shipping + self.tax


class Cart:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self._items: dict[str, int] = {}

    def add(self, sku: str, qty: int = 1) -> None:
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ValidationError(f"수량은 양의 정수여야 합니다: {sku} {qty!r}")
        self.catalog.resolve(sku)
        self._items[sku] = self._items.get(sku, 0) + qty

    def set_qty(self, sku: str, qty: int) -> None:
        if qty == 0:
            self.remove(sku)
            return
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
            raise ValidationError(f"수량은 0 이상의 정수여야 합니다: {sku} {qty!r}")
        self.catalog.resolve(sku)
        self._items[sku] = qty

    def remove(self, sku: str) -> None:
        self._items.pop(sku, None)

    def items(self) -> list[tuple[str, int]]:
        return list(self._items.items())

    def is_empty(self) -> bool:
        return not self._items

    def quote(self, *, region: str, coupons: list[Coupon], tax_table: TaxTable, today: date) -> Quote:
        if self.is_empty():
            raise ValidationError("장바구니가 비었습니다")
        check_region(region)
        priced: list[PricedLine] = []
        for sku, qty in self._items.items():
            s = self.catalog.resolve(sku)
            product = self.catalog.product(s.product_sku)
            pct = Decimal("0")
            for min_qty, p in product.tiers:
                if qty >= min_qty:
                    pct = p
            unit = (s.price * (100 - pct) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            priced.append(PricedLine(sku=s.sku, product_sku=s.product_sku, name=s.name, category=s.category,
                                     qty=qty, list_price=s.price, unit_price=unit, weight_g=s.weight_g))
        subtotal = total(p.amount for p in priced)
        check_coupons(coupons, subtotal, today)
        discounts, free_shipping = apply_coupons(priced, coupons)
        lines = []
        for p, d in zip(priced, discounts):
            rate = tax_table.rate_for(p.category)
            lines.append(QuoteLine(sku=p.sku, name=p.name, category=p.category, qty=p.qty, list_price=p.list_price,
                                   unit_price=p.unit_price, discount=d, tax_rate=rate, tax=line_tax(p.amount - d, rate)))
        weight = sum(p.weight_g * p.qty for p in priced)
        shipping = ZERO if free_shipping else shipping_cost(region, weight, subtotal)
        return Quote(lines=lines, shipping=shipping, shipping_tax=line_tax(shipping, tax_table.shipping_rate))
