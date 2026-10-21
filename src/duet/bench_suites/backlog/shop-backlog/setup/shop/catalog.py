"""상품 목록(catalog).

- 상품(Product): SKU, 이름, 카테고리, 가격(세금 제외), 무게(g), 수량 할인 구간(tiers), 판매 여부(active).
- 변형(Variant): 상품의 색·크기 같은 선택지. 변형이 하나라도 있는 상품은 그 자체로는 팔 수 없고
  변형 SKU 로 주문한다. 변형의 price·weight_g 가 None 이면 상품의 값을 쓴다.
- 판매 단위(Sellable): 주문할 수 있는 SKU 하나를 해석한 결과(`Catalog.resolve`).
  변형의 이름은 "상품 이름 (속성값, 속성값)" 이다. 속성이 없으면 "상품 이름 (변형 SKU)".
- 수량 할인 구간: [(최소 수량, 할인율 %), ...]. 주문 수량 이상인 구간 중 최소 수량이 가장 큰 것을 쓴다.
  할인 단가 계산은 pricing 모듈이 한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from .errors import NotFound, ValidationError
from .money import parse_money, to_decimal

SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,31}$")
CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


@dataclass
class Product:
    sku: str
    name: str
    category: str
    price: Decimal
    weight_g: int = 0
    tiers: list[tuple[int, Decimal]] = field(default_factory=list)
    active: bool = True


@dataclass
class Variant:
    sku: str
    product_sku: str
    attrs: dict[str, str] = field(default_factory=dict)
    price: Decimal | None = None
    weight_g: int | None = None


@dataclass(frozen=True)
class Sellable:
    sku: str
    product_sku: str
    name: str
    category: str
    price: Decimal
    weight_g: int


def check_sku(sku: object) -> str:
    if not isinstance(sku, str) or not SKU_RE.match(sku):
        raise ValidationError(f"SKU 형식이 아닙니다: {sku!r} (대문자·숫자·'-', 32자 이하)")
    return sku


def check_category(category: object) -> str:
    if not isinstance(category, str) or not CATEGORY_RE.match(category):
        raise ValidationError(f"카테고리 형식이 아닙니다: {category!r} (소문자로 시작)")
    return category


def check_weight(weight_g: object) -> int:
    try:
        w = int(weight_g)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValidationError(f"무게는 정수(g)여야 합니다: {weight_g!r}") from None
    if w < 0 or str(w) != str(weight_g).strip():
        raise ValidationError(f"무게는 0 이상의 정수(g)여야 합니다: {weight_g!r}")
    return w


def parse_tiers(tiers: object) -> list[tuple[int, Decimal]]:
    """[(min_qty, pct), ...] 또는 "10:5,50:10" 문자열.

    min_qty 는 2 이상 정수, pct 는 0 초과 100 미만. 같은 최소 수량을 두 번 줄 수 없다. 최소 수량 순으로 정렬한다.
    """
    if tiers is None or tiers == "":
        return []
    if isinstance(tiers, str):
        pairs = []
        for part in tiers.split(","):
            part = part.strip()
            if not part:
                continue
            if ":" not in part:
                raise ValidationError(f"수량 할인 구간 형식이 아닙니다: {part!r} (최소수량:할인율)")
            q, p = part.split(":", 1)
            pairs.append((q.strip(), p.strip()))
        tiers = pairs
    out: list[tuple[int, Decimal]] = []
    seen: set[int] = set()
    for q, p in tiers:  # type: ignore[union-attr]
        try:
            min_qty = int(q)
        except (TypeError, ValueError):
            raise ValidationError(f"수량 할인 구간의 최소 수량이 정수가 아닙니다: {q!r}") from None
        if min_qty < 2:
            raise ValidationError(f"수량 할인 구간의 최소 수량은 2 이상입니다: {min_qty}")
        pct = to_decimal(p)
        if not (0 < pct < 100):
            raise ValidationError(f"수량 할인율은 0 초과 100 미만입니다: {p}")
        if min_qty in seen:
            raise ValidationError(f"같은 최소 수량의 구간이 두 번 있습니다: {min_qty}")
        seen.add(min_qty)
        out.append((min_qty, pct))
    return sorted(out)


def variant_name(product: Product, variant: Variant) -> str:
    if variant.attrs:
        return f"{product.name} ({', '.join(variant.attrs.values())})"
    return f"{product.name} ({variant.sku})"


class Catalog:
    def __init__(self) -> None:
        self._products: dict[str, Product] = {}
        self._variants: dict[str, Variant] = {}

    # ------------------------------------------------------------------ 추가·변경
    def _check_new_sku(self, sku: str) -> None:
        check_sku(sku)
        if sku in self._products or sku in self._variants:
            raise ValidationError(f"이미 있는 SKU: {sku}")

    def add_product(self, sku: str, name: str, category: str, price: object, *, weight_g: object = 0,
                    tiers: object = None, active: bool = True) -> Product:
        self._check_new_sku(sku)
        name = (name or "").strip()
        if not name:
            raise ValidationError("상품 이름이 비었습니다")
        product = Product(sku=sku, name=name, category=check_category(category), price=parse_money(price),
                          weight_g=check_weight(weight_g), tiers=parse_tiers(tiers), active=bool(active))
        self._products[sku] = product
        return product

    def add_variant(self, product_sku: str, sku: str, *, attrs: dict[str, str] | None = None,
                    price: object = None, weight_g: object = None) -> Variant:
        product = self.product(product_sku)
        self._check_new_sku(sku)
        clean: dict[str, str] = {}
        for k, v in (attrs or {}).items():
            k, v = str(k).strip(), str(v).strip()
            if not k or not v:
                raise ValidationError("변형 속성의 이름과 값은 비어 있을 수 없습니다")
            clean[k] = v
        variant = Variant(sku=sku, product_sku=product.sku, attrs=clean,
                          price=None if price is None else parse_money(price),
                          weight_g=None if weight_g is None else check_weight(weight_g))
        self._variants[sku] = variant
        return variant

    def set_active(self, sku: str, active: bool) -> None:
        self.product(sku).active = bool(active)

    def set_price(self, sku: str, price: object) -> None:
        """상품 또는 변형의 가격을 바꾼다. 이미 만든 주문에는 영향이 없다."""
        if sku in self._variants:
            self._variants[sku].price = parse_money(price)
        else:
            self.product(sku).price = parse_money(price)

    # ------------------------------------------------------------------ 조회
    def product(self, sku: str) -> Product:
        try:
            return self._products[sku]
        except KeyError:
            raise NotFound(f"없는 상품: {sku}") from None

    def variant(self, sku: str) -> Variant:
        try:
            return self._variants[sku]
        except KeyError:
            raise NotFound(f"없는 변형: {sku}") from None

    def products(self) -> list[Product]:
        return [self._products[k] for k in sorted(self._products)]

    def variants(self) -> list[Variant]:
        return [self._variants[k] for k in sorted(self._variants)]

    def variants_of(self, product_sku: str) -> list[Variant]:
        return [v for v in self.variants() if v.product_sku == product_sku]

    def has_variants(self, product_sku: str) -> bool:
        return any(v.product_sku == product_sku for v in self._variants.values())

    def __contains__(self, sku: object) -> bool:
        return sku in self._products or sku in self._variants

    def _sellable(self, product: Product, variant: Variant | None) -> Sellable:
        if variant is None:
            return Sellable(product.sku, product.sku, product.name, product.category, product.price, product.weight_g)
        return Sellable(variant.sku, product.sku, variant_name(product, variant), product.category,
                        variant.price if variant.price is not None else product.price,
                        variant.weight_g if variant.weight_g is not None else product.weight_g)

    def resolve(self, sku: str) -> Sellable:
        """주문할 수 있는 SKU 를 판매 단위로. 판매 중지 상품, 변형이 있는 상품 SKU 는 ValidationError."""
        if sku in self._variants:
            variant = self._variants[sku]
            product = self._products[variant.product_sku]
            if not product.active:
                raise ValidationError(f"판매 중지된 상품: {sku}")
            return self._sellable(product, variant)
        if sku in self._products:
            product = self._products[sku]
            if self.has_variants(sku):
                raise ValidationError(f"변형을 골라 주문해야 합니다: {sku}")
            if not product.active:
                raise ValidationError(f"판매 중지된 상품: {sku}")
            return self._sellable(product, None)
        raise NotFound(f"없는 상품: {sku}")

    def sellables(self, *, include_inactive: bool = False) -> list[Sellable]:
        """주문할 수 있는 단위 전부, SKU 순. 변형이 있는 상품은 변형들로 나온다."""
        out = []
        for product in self.products():
            if not product.active and not include_inactive:
                continue
            variants = self.variants_of(product.sku)
            if variants:
                out.extend(self._sellable(product, v) for v in variants)
            else:
                out.append(self._sellable(product, None))
        return sorted(out, key=lambda s: s.sku)

    def search(self, text: str) -> list[Sellable]:
        """이름·SKU·카테고리에 text 가 들어 있는 판매 단위 (대소문자 무시), SKU 순. 판매 중지 상품은 빼고."""
        needle = text.strip().casefold()
        if not needle:
            return []
        return [s for s in self.sellables()
                if needle in s.sku.casefold() or needle in s.name.casefold() or needle in s.category]

    def tier_percent(self, product_sku: str, qty: int) -> Decimal:
        """그 상품의 수량 할인율(%). 구간이 없거나 수량이 모자라면 0."""
        pct = Decimal("0")
        for min_qty, p in self.product(product_sku).tiers:
            if qty >= min_qty:
                pct = p
        return pct
