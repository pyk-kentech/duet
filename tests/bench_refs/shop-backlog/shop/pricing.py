"""가격 계산: 줄 단가(수량 할인)와 쿠폰.

## 줄 단가
- 단가 = 판매 단위의 가격(변형 가격이 없으면 상품 가격).
- 수량 할인: **같은 상품(product)에 속한 줄들의 수량 합**으로 상품의 구간을 고른다(변형이 없는 상품은 그 줄의
  수량). 고른 할인율을 각 줄의 **단가에** 적용해 센트로 반올림한 뒤 수량을 곱한다.
  (예: 0.99 에 5% -> 단가 0.94, 10개면 9.40. 줄 금액에서 한 번 반올림하면 9.41 이 되므로 다르다.)
  견적(cart)·주문(checkout)·다시 계산(reprice) 모두 `tier_quantities` + `unit_price_for` 를 쓴다.
- 같은 SKU 를 여러 번 주면 처음 나온 자리에서 한 줄로 합친다.

## 쿠폰 (Coupon)
종류(kind):
- `percent`: 주문 금액의 value% 할인.
- `fixed`: value 금액 할인 (남은 금액을 넘지 않는다).
- `category_percent`: category 가 같은 줄들만 value% 할인. category 필수.
- `free_shipping`: 배송비 0.
- `bundle`: N+1 묶음. value = N(1 이상의 정수), category 필수. 그 카테고리의 각 줄마다 수량 // (N+1) 개가 무료
  (할인 = 무료 개수 x 그 줄의 할인 단가, 줄의 남은 금액을 넘지 않음). 줄마다 따로 센다.

규칙:
- 코드는 대소문자를 가리지 않는다(대문자로 저장). 영문 대문자·숫자 3~20자.
- 만료일(expires)이 있으면 그날까지 쓸 수 있다(그날 포함).
- max_uses 가 있으면 uses 가 그 수에 닿은 쿠폰은 쓸 수 없다. 주문이 만들어질 때 uses 가 1 오른다.
- min_subtotal: 쿠폰 할인 전 소계(수량 할인 뒤)가 이 금액 이상이어야 한다.
- 함께 쓰기: free_shipping 을 뺀 쿠폰이 둘 이상이면 모두 stackable 이어야 한다.
  free_shipping 쿠폰은 stackable 값과 상관없이 다른 쿠폰과 함께 쓸 수 있다.
- 같은 코드를 두 번 쓸 수 없다.

적용 순서: bundle -> category_percent -> percent -> fixed. 같은 종류는 준 순서대로. 각 쿠폰은 앞의 쿠폰이 깎고 남은
금액에 적용한다. category_percent 는 줄마다 반올림, percent·fixed 는 주문 전체 할인액을 구해
줄들의 남은 금액 비율로 나눈다(money.allocate). 줄마다 쌓인 할인이 그 줄의 discount 가 된다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from .catalog import Catalog, check_category
from .errors import CouponError, ValidationError
from .money import ZERO, allocate, parse_money, parse_percent, percent_of, round_money, to_decimal, total

COUPON_KINDS = ("percent", "fixed", "category_percent", "free_shipping", "bundle")
CODE_RE = re.compile(r"^[A-Z0-9]{3,20}$")
_ORDER = {"bundle": 0, "category_percent": 1, "percent": 2, "fixed": 3}
CATEGORY_KINDS = ("category_percent", "bundle")


@dataclass
class Coupon:
    code: str
    kind: str
    value: Decimal = Decimal("0")
    category: str | None = None
    min_subtotal: Decimal = Decimal("0")
    stackable: bool = False
    expires: date | None = None
    max_uses: int | None = None
    uses: int = 0


def normalize_code(code: str) -> str:
    c = (code or "").strip().upper()
    if not CODE_RE.match(c):
        raise ValidationError(f"쿠폰 코드 형식이 아닙니다: {code!r} (영문·숫자 3~20자)")
    return c


def make_coupon(code: str, kind: str, value: object = 0, *, category: str | None = None,
                min_subtotal: object = 0, stackable: bool = False, expires: date | str | None = None,
                max_uses: int | None = None, uses: int = 0) -> Coupon:
    code = normalize_code(code)
    if kind not in COUPON_KINDS:
        raise ValidationError(f"모르는 쿠폰 종류: {kind} (가능: {', '.join(COUPON_KINDS)})")
    if kind in ("percent", "category_percent"):
        val = parse_percent(value)
    elif kind == "fixed":
        val = parse_money(value)
        if val <= 0:
            raise ValidationError("fixed 쿠폰의 금액은 0 보다 커야 합니다")
    elif kind == "bundle":
        n = to_decimal(value)
        if n != n.to_integral_value() or n < 1:
            raise ValidationError(f"bundle 쿠폰의 값은 1 이상의 정수입니다: {value}")
        val = Decimal(int(n))
    else:
        val = parse_money(value or 0)
        if val != 0:
            raise ValidationError("free_shipping 쿠폰에는 값을 주지 않습니다")
        val = Decimal("0")
    if kind in CATEGORY_KINDS:
        if not category:
            raise ValidationError(f"{kind} 쿠폰에는 category 가 필요합니다")
        category = check_category(category)
    elif category:
        raise ValidationError(f"{kind} 쿠폰에는 category 를 줄 수 없습니다")
    else:
        category = None
    if isinstance(expires, str):
        try:
            expires = date.fromisoformat(expires)
        except ValueError:
            raise ValidationError(f"만료일 형식이 아닙니다: {expires!r} (YYYY-MM-DD)") from None
    if max_uses is not None and (isinstance(max_uses, bool) or not isinstance(max_uses, int) or max_uses < 1):
        raise ValidationError(f"max_uses 는 1 이상의 정수입니다: {max_uses!r}")
    if isinstance(uses, bool) or not isinstance(uses, int) or uses < 0:
        raise ValidationError(f"uses 는 0 이상의 정수입니다: {uses!r}")
    return Coupon(code=code, kind=kind, value=val, category=category, min_subtotal=parse_money(min_subtotal),
                  stackable=bool(stackable), expires=expires, max_uses=max_uses, uses=uses)


@dataclass
class PricedLine:
    sku: str
    product_sku: str
    name: str
    category: str
    qty: int
    list_price: Decimal
    unit_price: Decimal
    weight_g: int

    @property
    def amount(self) -> Decimal:
        return self.unit_price * self.qty


def merge_items(items: Iterable[tuple[str, int]]) -> list[tuple[str, int]]:
    """같은 SKU 는 처음 나온 자리에서 합친다. 수량은 양의 정수."""
    merged: dict[str, int] = {}
    for sku, qty in items:
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ValidationError(f"수량은 양의 정수여야 합니다: {sku} {qty!r}")
        merged[sku] = merged.get(sku, 0) + qty
    if not merged:
        raise ValidationError("주문할 상품이 없습니다")
    return list(merged.items())


def tier_quantities(lines: Iterable[tuple[str, int]]) -> dict[str, int]:
    """상품 SKU -> 그 상품에 속한 줄들의 수량 합. lines: (product_sku, qty)."""
    qty_by_product: dict[str, int] = {}
    for product_sku, qty in lines:
        qty_by_product[product_sku] = qty_by_product.get(product_sku, 0) + qty
    return qty_by_product


def unit_price_for(catalog: Catalog, price: Decimal, product_sku: str, product_qty: int) -> Decimal:
    """수량 할인 뒤 단가. product_qty 는 그 상품 전체 수량."""
    pct = catalog.tier_percent(product_sku, product_qty)
    return round_money(price * (100 - pct) / 100)


def price_sellables(catalog: Catalog, items: list[tuple[object, int]]) -> list[PricedLine]:
    """[(Sellable, qty)] -> PricedLine. 수량 할인 구간은 상품별 수량 합으로 고른다."""
    qty_by_product = tier_quantities((s.product_sku, qty) for s, qty in items)
    return [PricedLine(sku=s.sku, product_sku=s.product_sku, name=s.name, category=s.category, qty=qty,
                       list_price=s.price, weight_g=s.weight_g,
                       unit_price=unit_price_for(catalog, s.price, s.product_sku, qty_by_product[s.product_sku]))
            for s, qty in items]


def price_lines(catalog: Catalog, items: Iterable[tuple[str, int]]) -> list[PricedLine]:
    """주문 줄의 단가를 정한다(수량 할인 포함)."""
    return price_sellables(catalog, [(catalog.resolve(sku), qty) for sku, qty in merge_items(items)])


def line_total(unit_price: Decimal, qty: int, pct: Decimal = Decimal("0")) -> Decimal:
    """(0.6 이전 API, 쓰는 곳 없음 — 외부 스크립트 호환용으로 남겨 둠) 수량 할인 뒤 줄 금액."""
    return round_money(unit_price * (100 - pct) / 100) * qty


def check_coupons(coupons: list[Coupon], subtotal: Decimal, today: date) -> None:
    seen: set[str] = set()
    for c in coupons:
        if c.code in seen:
            raise CouponError(f"같은 쿠폰을 두 번 쓸 수 없습니다: {c.code}")
        seen.add(c.code)
        if c.expires is not None and today > c.expires:
            raise CouponError(f"만료된 쿠폰: {c.code}")
        if c.max_uses is not None and c.uses >= c.max_uses:
            raise CouponError(f"사용 한도를 다 쓴 쿠폰: {c.code}")
        if subtotal < c.min_subtotal:
            raise CouponError(f"최소 주문 금액({c.min_subtotal})이 안 됩니다: {c.code}")
    limited = [c for c in coupons if c.kind != "free_shipping"]
    if len(limited) > 1 and not all(c.stackable for c in limited):
        raise CouponError("함께 쓸 수 없는 쿠폰입니다: " + ", ".join(c.code for c in limited))


def apply_coupons(lines: list[PricedLine], coupons: list[Coupon]) -> tuple[list[Decimal], bool]:
    """줄마다의 쿠폰 할인액과 무료 배송 여부."""
    amounts = [line.amount for line in lines]
    disc = [ZERO for _ in lines]
    ordered = sorted((c for c in coupons if c.kind in _ORDER), key=lambda c: _ORDER[c.kind])
    for c in ordered:
        remaining = [a - d for a, d in zip(amounts, disc)]
        if c.kind == "bundle":
            n = int(c.value)
            for i, line in enumerate(lines):
                if line.category == c.category:
                    free = line.qty // (n + 1)
                    disc[i] += min(free * line.unit_price, remaining[i])
        elif c.kind == "category_percent":
            for i, line in enumerate(lines):
                if line.category == c.category:
                    disc[i] += percent_of(remaining[i], c.value)
        elif c.kind == "percent":
            off = percent_of(total(remaining), c.value)
            for i, part in enumerate(allocate(off, remaining)):
                disc[i] += part
        elif c.kind == "fixed":
            off = min(c.value, total(remaining))
            for i, part in enumerate(allocate(off, remaining)):
                disc[i] += part
    free_shipping = any(c.kind == "free_shipping" for c in coupons)
    return disc, free_shipping
