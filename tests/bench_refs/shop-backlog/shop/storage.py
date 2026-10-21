"""JSON 데이터 파일 읽기·쓰기.

- 형식 버전은 최상위 `version` 이다. `save` 는 언제나 지금 버전(FORMAT_VERSION = 3)으로 쓴다.
- `load` 는 버전 1, 2, 3 을 읽는다. 그 밖의 버전, 깨진 JSON, 빠진 필드는 StorageError.
- 버전 3: Decimal 값은 모두 JSON 문자열. 금액은 소수 둘째 자리("19.90"), 비율(세율·할인율·쿠폰 백분율·
  bundle 의 N)은 뒤의 0 없는 문자열("7", "7.5"). 주문에 판매 채널 "channel".
- 파일이 없으면 빈 가게를 돌려준다.
- 쓰기는 같은 폴더의 임시 파일에 쓴 뒤 `os.replace` 로 바꾼다.
- 파일 내용을 믿지 않는다: 쿠폰 종류·주문 상태는 아는 값인지 확인한다.

형식의 자세한 모양은 DESIGN.md 의 '데이터 파일' 절을 본다.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from .errors import ShopError, StorageError
from .money import fmt, to_decimal
from .orders import Event, Order, OrderLine, Refund, check_channel
from .pricing import Coupon, make_coupon
from .store import FIRST_ORDER_ID, Shop
from .tax import TaxTable

FORMAT_VERSION = 3
_KINDS = ("percent", "fixed", "category_percent", "free_shipping", "bundle")
_STATUSES = ("pending", "paid", "shipped", "cancelled", "refunded")


# ====================================================================== 쓰기
def _m(value: Decimal) -> str:
    """금액: 소수 둘째 자리 문자열."""
    return fmt(value)


def _opt_m(value: Decimal | None) -> str | None:
    return None if value is None else fmt(value)


def _r(value: Decimal) -> str:
    """비율·개수: 뒤의 0 없는 문자열 ("7", "7.5", "10")."""
    text = format(value.normalize(), "f")
    return text


def _coupon_value(coupon: Coupon) -> str:
    return _m(coupon.value) if coupon.kind == "fixed" else _r(coupon.value)


def _dt(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def to_data(shop: Shop) -> dict[str, Any]:
    cat = shop.catalog
    return {
        "version": FORMAT_VERSION,
        "settings": {"locale": shop.settings.locale, "tax_display": shop.settings.tax_display},
        "tax": {"default": _r(shop.tax_table.default),
                "rates": {k: _r(v) for k, v in sorted(shop.tax_table.rates.items())}},
        "products": [{"sku": p.sku, "name": p.name, "category": p.category, "price": _m(p.price),
                      "weight_g": p.weight_g, "tiers": [[q, _r(pct)] for q, pct in p.tiers], "active": p.active}
                     for p in cat.products()],
        "variants": [{"sku": v.sku, "product_sku": v.product_sku, "attrs": dict(v.attrs), "price": _opt_m(v.price),
                      "weight_g": v.weight_g} for v in cat.variants()],
        "stock": {"on_hand": dict(sorted(shop.inventory.on_hand.items())),
                  "reserved": dict(sorted(shop.inventory.reserved.items()))},
        "coupons": [{"code": c.code, "kind": c.kind, "value": _coupon_value(c), "category": c.category,
                     "min_subtotal": _m(c.min_subtotal), "stackable": c.stackable,
                     "expires": c.expires.isoformat() if c.expires else None, "max_uses": c.max_uses,
                     "uses": c.uses} for c in shop.coupons_list()],
        "orders": [{"id": o.id, "created": _dt(o.created), "customer": o.customer, "region": o.region,
                    "status": o.status, "coupons": list(o.coupons), "shipping": _m(o.shipping),
                    "shipping_tax": _m(o.shipping_tax), "paid_at": _dt(o.paid_at), "shipped_at": _dt(o.shipped_at),
                    "channel": o.channel,
                    "lines": [{"sku": ln.sku, "name": ln.name, "category": ln.category, "qty": ln.qty,
                               "list_price": _m(ln.list_price), "unit_price": _m(ln.unit_price),
                               "discount": _m(ln.discount), "tax_rate": _r(ln.tax_rate), "tax": _m(ln.tax)}
                              for ln in o.lines]}
                   for o in shop.orders],
        "refunds": [{"id": r.id, "order_id": r.order_id, "created": _dt(r.created), "items": dict(r.items),
                     "net": _m(r.net), "shipping": _m(r.shipping), "tax": _m(r.tax), "reason": r.reason}
                    for r in shop.refunds],
        "events": [{"ts": _dt(e.ts), "order_id": e.order_id, "kind": e.kind, "detail": e.detail} for e in shop.events],
        "next_order_id": shop.next_order_id,
        "next_refund_id": shop.next_refund_id,
    }


def save(shop: Shop, path: str | Path) -> None:
    path = Path(path)
    data = to_data(shop)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".shop-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ====================================================================== 읽기
def _d(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise StorageError(f"숫자가 아닌 값: {value!r}")
    return to_decimal(value)


def _cents(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StorageError(f"센트 값은 정수여야 합니다: {value!r}")
    return Decimal(value) / 100


def _opt_dt(value: Any) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _check_kind(kind: str) -> str:
    if kind not in _KINDS:
        raise StorageError(f"모르는 쿠폰 종류: {kind}")
    return kind


def _check_status(status: str) -> str:
    if status not in _STATUSES:
        raise StorageError(f"모르는 주문 상태: {status}")
    return status


def _finish(shop: Shop, next_order_id: int | None, next_refund_id: int | None) -> Shop:
    if next_order_id is None:
        next_order_id = max((o.id for o in shop.orders), default=FIRST_ORDER_ID - 1) + 1
    if next_refund_id is None:
        next_refund_id = max((r.id for r in shop.refunds), default=0) + 1
    shop.next_order_id = next_order_id
    shop.next_refund_id = next_refund_id
    return shop


def _from_v1(data: dict[str, Any], shop: Shop) -> Shop:
    shop.settings.set("locale", data.get("locale", "default"))
    for p in data["products"]:
        shop.catalog.add_product(p["sku"], p["name"], p["category"], _cents(p["price_cents"]),
                                 weight_g=p.get("weight_g", 0), active=p.get("active", True))
    for sku, st in data.get("stock", {}).items():
        if st.get("on_hand"):
            shop.inventory.on_hand[sku] = int(st["on_hand"])
        if st.get("reserved"):
            shop.inventory.reserved[sku] = int(st["reserved"])
    for c in data.get("coupons", []):
        kind = _check_kind(c["kind"])
        value = _cents(c["value"]) if kind == "fixed" else Decimal(c["value"])
        coupon = make_coupon(c["code"], kind, value, category=c.get("category"),
                             min_subtotal=_cents(c.get("min_cents", 0)), expires=c.get("expires"), uses=c.get("uses", 0))
        shop.coupons[coupon.code] = coupon
    for o in data.get("orders", []):
        lines = [OrderLine(sku=ln["sku"], name=ln["name"], category=ln["category"], qty=int(ln["qty"]),
                           list_price=_cents(ln["price_cents"]), unit_price=_cents(ln["price_cents"]),
                           discount=_cents(ln["discount_cents"]), tax_rate=_d(ln["tax_rate"]),
                           tax=_cents(ln["tax_cents"]))
                 for ln in o["lines"]]
        shop.orders.append(Order(id=int(o["id"]), created=datetime.fromisoformat(o["created"]), customer=o["customer"],
                                 region="domestic", lines=lines, coupons=list(o.get("coupons", [])),
                                 shipping=_cents(o["shipping_cents"]), shipping_tax=_cents(o["shipping_tax_cents"]),
                                 status=_check_status(o["status"])))
    for r in data.get("refunds", []):
        shop.refunds.append(Refund(id=int(r["id"]), order_id=int(r["order_id"]), created=datetime.fromisoformat(r["created"]),
                                   items={k: int(v) for k, v in r["items"].items()}, net=_cents(r["net_cents"]),
                                   shipping=_cents(r["shipping_cents"]), tax=_cents(r["tax_cents"])))
    return _finish(shop, None, None)


def _from_v2(data: dict[str, Any], shop: Shop, *, version: int = 2) -> Shop:
    """버전 2 와 3 은 구조가 같다. 3 은 값이 문자열이고 주문에 channel 이 있다."""
    settings = data.get("settings", {})
    for key in ("locale", "tax_display"):
        if key in settings:
            shop.settings.set(key, settings[key])
    tax = data.get("tax")
    if tax is not None:
        shop.tax_table = TaxTable({k: _d(v) for k, v in tax["rates"].items()}, default=_d(tax["default"]))
    for p in data["products"]:
        shop.catalog.add_product(p["sku"], p["name"], p["category"], _d(p["price"]), weight_g=p.get("weight_g", 0),
                                 tiers=[(q, _d(pct)) for q, pct in p.get("tiers", [])], active=p.get("active", True))
    for v in data.get("variants", []):
        shop.catalog.add_variant(v["product_sku"], v["sku"], attrs=v.get("attrs") or {},
                                 price=None if v.get("price") is None else _d(v["price"]), weight_g=v.get("weight_g"))
    stock = data.get("stock", {})
    shop.inventory.on_hand = {k: int(q) for k, q in stock.get("on_hand", {}).items()}
    shop.inventory.reserved = {k: int(q) for k, q in stock.get("reserved", {}).items()}
    for c in data.get("coupons", []):
        coupon: Coupon = make_coupon(c["code"], _check_kind(c["kind"]), _d(c["value"]), category=c.get("category"),
                                     min_subtotal=_d(c.get("min_subtotal", 0)), stackable=c.get("stackable", False),
                                     expires=c.get("expires"), max_uses=c.get("max_uses"), uses=c.get("uses", 0))
        shop.coupons[coupon.code] = coupon
    for o in data.get("orders", []):
        lines = [OrderLine(sku=ln["sku"], name=ln["name"], category=ln["category"], qty=int(ln["qty"]),
                           list_price=_d(ln["list_price"]), unit_price=_d(ln["unit_price"]), discount=_d(ln["discount"]),
                           tax_rate=_d(ln["tax_rate"]), tax=_d(ln["tax"]))
                 for ln in o["lines"]]
        shop.orders.append(Order(id=int(o["id"]), created=datetime.fromisoformat(o["created"]), customer=o["customer"],
                                 region=o.get("region", "domestic"), lines=lines, coupons=list(o.get("coupons", [])),
                                 shipping=_d(o["shipping"]), shipping_tax=_d(o["shipping_tax"]),
                                 status=_check_status(o["status"]), paid_at=_opt_dt(o.get("paid_at")),
                                 shipped_at=_opt_dt(o.get("shipped_at")),
                                 channel=check_channel(o.get("channel", "web")) if version >= 3 else "web"))
    for r in data.get("refunds", []):
        shop.refunds.append(Refund(id=int(r["id"]), order_id=int(r["order_id"]), created=datetime.fromisoformat(r["created"]),
                                   items={k: int(v) for k, v in r["items"].items()}, net=_d(r["net"]),
                                   shipping=_d(r["shipping"]), tax=_d(r["tax"]), reason=r.get("reason", "")))
    for e in data.get("events", []):
        shop.events.append(Event(ts=datetime.fromisoformat(e["ts"]), order_id=int(e["order_id"]), kind=e["kind"],
                                 detail=e.get("detail", "")))
    return _finish(shop, data.get("next_order_id"), data.get("next_refund_id"))


def load(path: str | Path, clock: Callable[[], datetime] | None = None) -> Shop:
    path = Path(path)
    shop = Shop(clock=clock)
    if not path.exists():
        return shop
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise StorageError(f"데이터 파일을 읽을 수 없습니다: {path} ({e})") from None
    if not isinstance(data, dict):
        raise StorageError(f"데이터 파일 형식이 아닙니다: {path}")
    version = data.get("version")
    try:
        if version == 1:
            return _from_v1(data, shop)
        if version in (2, 3):
            return _from_v2(data, shop, version=version)
    except StorageError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, ShopError) as e:
        raise StorageError(f"깨진 데이터 파일: {path} ({type(e).__name__}: {e})") from None
    raise StorageError(f"지원하지 않는 형식 버전: {version!r}")

