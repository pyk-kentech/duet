"""명령줄 도구: python -m shop [--data 파일] <명령> ...

- 데이터 파일 기본값은 ./shop.json. 바꾸는 명령만 파일에 쓴다(읽기 명령은 파일을 건드리지 않는다).
- 현재 시각은 환경 변수 SHOP_NOW(ISO 시각, 테스트용)가 있으면 그것, 없으면 실제 시각.
- 오류는 표준 오류에 "오류: ..." 를 쓰고 종료 코드 1. 이때 파일은 바뀌지 않는다.
- 상품 목록 인자 ITEM 은 "SKU:수량" 또는 "SKU"(수량 1).
- 출력 형식은 README.md 에 있다. 다른 도구가 출력을 읽으므로 형식을 함부로 바꾸지 않는다.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from . import csvio, customers, reports, storage
from .errors import ShopError, ValidationError
from .money import fmt, total
from .store import Settings, Shop
from .tax import format_rate, gross

DEFAULT_DATA = "shop.json"


# ====================================================================== 보조
def _clock() -> datetime:
    text = os.environ.get("SHOP_NOW")
    if text:
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            raise ValidationError(f"SHOP_NOW 형식이 아닙니다: {text!r}") from None
    return datetime.now()


def _date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValidationError(f"날짜 형식이 아닙니다: {text!r} (YYYY-MM-DD)") from None


def _items(specs: list[str]) -> list[tuple[str, int]]:
    out = []
    for spec in specs:
        sku, sep, qty = spec.partition(":")
        if not sep:
            out.append((sku, 1))
            continue
        try:
            n = int(qty)
        except ValueError:
            raise ValidationError(f"상품 인자 형식이 아닙니다: {spec!r} (SKU:수량)") from None
        out.append((sku, n))
    return out


def _attrs(specs: list[str]) -> dict[str, str]:
    out = {}
    for spec in specs or []:
        key, sep, value = spec.partition("=")
        if not sep:
            raise ValidationError(f"속성 형식이 아닙니다: {spec!r} (KEY=VALUE)")
        out[key] = value
    return out


def _coupon_value(coupon) -> str:
    if coupon.kind in ("percent", "category_percent"):
        return f"{format_rate(coupon.value)}%"
    if coupon.kind == "fixed":
        return fmt(coupon.value)
    if coupon.kind == "bundle":
        return f"{int(coupon.value)}+1"
    return "-"


# ====================================================================== 표시
def _line_text(line, settings: Settings) -> str:
    if settings.tax_display == "inclusive":
        unit, amount = gross(line.unit_price, line.tax_rate), gross(line.amount, line.tax_rate)
    else:
        unit, amount = line.unit_price, line.amount
    return f"  {line.sku}  {line.name}  {line.qty} x {fmt(unit)} = {fmt(amount)}"


def _totals_text(x) -> list[str]:
    out = [f"소계: {fmt(x.subtotal)}"]
    if x.discount:
        out.append(f"할인: -{fmt(x.discount)}")
    out += [f"배송: {fmt(x.shipping)}", f"세금: {fmt(x.tax)}", f"합계: {fmt(x.total)}"]
    return out


def format_order(order, refunds, settings: Settings) -> list[str]:
    out = [f"주문 {order.id} ({order.status})", f"고객: {order.customer}",
           f"날짜: {order.created:%Y-%m-%d %H:%M}", f"지역: {order.region}"]
    if order.channel != "web":
        out.append(f"채널: {order.channel}")
    if order.coupons:
        out.append("쿠폰: " + ", ".join(order.coupons))
    out += [_line_text(line, settings) for line in order.lines]
    out += _totals_text(order)
    if refunds:
        out.append(f"환불: -{fmt(total(r.amount for r in refunds))}")
    return out


def format_quote(quote, settings: Settings) -> list[str]:
    return [_line_text(line, settings) for line in quote.lines] + _totals_text(quote)


# ====================================================================== 명령 (돌려주는 값: 파일을 써야 하나)
def cmd_product_add(shop: Shop, a) -> bool:
    shop.add_product(a.sku, a.name, a.category, a.price, weight_g=a.weight, tiers=a.tiers, active=not a.inactive)
    print(f"상품 추가: {a.sku}")
    return True


def cmd_variant_add(shop: Shop, a) -> bool:
    shop.add_variant(a.product, a.sku, attrs=_attrs(a.attr), price=a.price, weight_g=a.weight)
    print(f"변형 추가: {a.sku}")
    return True


def cmd_products(shop: Shop, a) -> bool:
    for s in shop.catalog.sellables():
        print(f"{s.sku}\t{s.name}\t{s.category}\t{fmt(s.price)}\t{shop.inventory.available(s.sku)}")
    return False


def cmd_variants(shop: Shop, a) -> bool:
    product = shop.catalog.product(a.product)
    for v in shop.catalog.variants_of(product.sku):
        s = shop.catalog._sellable(product, v)
        attrs = ",".join(f"{k}={val}" for k, val in v.attrs.items())
        print(f"{s.sku}	{s.name}	{fmt(s.price)}	{attrs}")
    return False


def cmd_price_set(shop: Shop, a) -> bool:
    shop.catalog.set_price(a.sku, a.price)
    print(f"가격: {a.sku} {fmt(a.price)}")
    return True


def cmd_set_active(active: bool) -> Callable[[Shop, argparse.Namespace], bool]:
    def run(shop: Shop, a) -> bool:
        shop.catalog.set_active(a.sku, active)
        print(f"{'판매 재개' if active else '판매 중지'}: {a.sku}")
        return True
    return run


def cmd_search(shop: Shop, a) -> bool:
    for s in shop.catalog.search(a.text):
        print(f"{s.sku}	{s.name}	{s.category}	{fmt(s.price)}")
    return False


def cmd_summary(shop: Shop, a) -> bool:
    for status, count, amount in shop.status_summary():
        print(f"{status}	{count}	{fmt(amount)}")
    return False


def cmd_receive(shop: Shop, a) -> bool:
    on_hand = shop.receive(a.sku, a.qty)
    print(f"재고: {a.sku} {on_hand}")
    return True


def cmd_stock(shop: Shop, a) -> bool:
    inv = shop.inventory
    for sku in inv.skus():
        print(f"{sku}\t{inv.on_hand.get(sku, 0)}\t{inv.reserved.get(sku, 0)}\t{inv.available(sku)}")
    return False


def cmd_low_stock(shop: Shop, a) -> bool:
    for sku, available in shop.low_stock(a.threshold):
        print(f"{sku}	{available}")
    return False


def cmd_history(shop: Shop, a) -> bool:
    for e in shop.history(a.id):
        print(f"{e.ts:%Y-%m-%d %H:%M}	{e.kind}	{e.detail}".rstrip("	"))
    return False


def cmd_tax_rate(shop: Shop, a) -> bool:
    shop.tax_table.set_rate(a.category, a.rate)
    print(f"세율: {a.category} {format_rate(shop.tax_table.rate_for(a.category))}%")
    return True


def cmd_tax_rates(shop: Shop, a) -> bool:
    for category, rate in shop.tax_table.items():
        print(f"{category}	{format_rate(rate)}%")
    print(f"*	{format_rate(shop.tax_table.default)}%")
    return False


def cmd_coupon_add(shop: Shop, a) -> bool:
    c = shop.add_coupon(a.code, a.kind, a.value, category=a.category, min_subtotal=a.min, stackable=a.stackable,
                        expires=a.expires, max_uses=a.max_uses)
    print(f"쿠폰 추가: {c.code}")
    return True


def cmd_coupon_rm(shop: Shop, a) -> bool:
    code = shop.coupon(a.code).code
    shop.remove_coupon(code)
    print(f"쿠폰 삭제: {code}")
    return True


def cmd_coupons(shop: Shop, a) -> bool:
    for c in shop.coupons_list():
        limit = "-" if c.max_uses is None else str(c.max_uses)
        print(f"{c.code}\t{c.kind}\t{_coupon_value(c)}\t{c.uses}/{limit}")
    return False


def cmd_quote(shop: Shop, a) -> bool:
    q = shop.quote(_items(a.items), region=a.region, coupons=a.coupon or [])
    print("\n".join(format_quote(q, shop.settings)))
    return False


def cmd_order(shop: Shop, a) -> bool:
    o = shop.checkout(_items(a.items), a.customer, region=a.region, coupons=a.coupon or [], channel=a.channel)
    print(f"주문 {o.id} 생성 (합계 {fmt(o.total)})")
    return True


def _status_cmd(action: str) -> Callable[[Shop, argparse.Namespace], bool]:
    def run(shop: Shop, a) -> bool:
        order = getattr(shop, action)(a.id)
        print(f"주문 {order.id}: {order.status}")
        return True
    return run


def cmd_reprice(shop: Shop, a) -> bool:
    o = shop.reprice(a.id)
    print(f"주문 {o.id} 다시 계산 (합계 {fmt(o.total)})")
    return True


def cmd_refund(shop: Shop, a) -> bool:
    if a.all == bool(a.items):
        raise ValidationError("환불할 상품(SKU:수량)을 주거나 --all 을 줘야 합니다 (둘 중 하나만)")
    items = None if a.all else dict(_merge(_items(a.items)))
    r = shop.refund(a.id, items, restock=a.restock)
    print(f"환불 {r.id}: {fmt(r.amount)}")
    return True


def _merge(items: list[tuple[str, int]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for sku, q in items:
        out[sku] = out.get(sku, 0) + q
    return out


def cmd_expire(shop: Shop, a) -> bool:
    if a.hours <= 0:
        raise ValidationError("--hours 는 양수여야 합니다")
    ids = shop.expire_pending(timedelta(hours=a.hours))
    print("취소: " + ", ".join(str(i) for i in ids) if ids else "취소할 주문 없음")
    return bool(ids)


def cmd_show(shop: Shop, a) -> bool:
    order = shop.get_order(a.id)
    print("\n".join(format_order(order, shop.refunds_for(order.id), shop.settings)))
    return False


def cmd_orders(shop: Shop, a) -> bool:
    for o in shop.orders_list(a.status, a.channel):
        print(f"{o.id}\t{o.created.date().isoformat()}\t{o.customer}\t{o.status}\t{fmt(o.total)}")
    return False


def cmd_report(shop: Shop, a) -> bool:
    if a.kind == "daily":
        if len(a.args) != 1:
            raise ValidationError("report daily DATE")
        r = reports.daily_sales(shop, _date(a.args[0]), channel=a.channel)
        print(f"date\t{r.day.isoformat()}")
        print(f"orders\t{r.orders}")
        for key in ("gross", "refunds", "net", "tax"):
            print(f"{key}\t{fmt(getattr(r, key))}")
    elif a.kind == "category":
        if len(a.args) != 2:
            raise ValidationError("report category FROM TO")
        for cat, amount in reports.sales_by_category(shop, _date(a.args[0]), _date(a.args[1]),
                                                     channel=a.channel).items():
            print(f"{cat}\t{fmt(amount)}")
    elif a.kind == "top":
        if a.args:
            raise ValidationError("report top [-n N] [--from DATE] [--to DATE]")
        start = _date(a.date_from) if a.date_from else None
        end = _date(a.date_to) if a.date_to else None
        for sku, name, qty in reports.top_products(shop, a.n, start, end, channel=a.channel):
            print(f"{sku}\t{name}\t{qty}")
    elif a.kind == "customers":
        if a.args or a.channel:
            raise ValidationError("report customers [--from DATE] [--to DATE]")
        start = _date(a.date_from) if a.date_from else None
        end = _date(a.date_to) if a.date_to else None
        for row in customers.customer_summary(shop, start, end):
            print(f"{row.customer}	{row.orders}	{fmt(row.spent)}	{fmt(row.refunded)}")
    else:  # tax
        if len(a.args) != 2:
            raise ValidationError("report tax FROM TO")
        for rate, net, tax in reports.tax_report(shop, _date(a.args[0]), _date(a.args[1]), channel=a.channel):
            print(f"{format_rate(rate)}%\t{fmt(net)}\t{fmt(tax)}")
    return False


def cmd_export(shop: Shop, a) -> bool:
    if a.what == "orders":
        n = csvio.export_orders(shop, a.file)
    elif a.what == "refunds":
        n = csvio.export_refunds(shop, a.file)
    else:
        n = csvio.export_products(shop, a.file)
    print(f"내보냄: {n}줄")
    return False


def cmd_import(shop: Shop, a) -> bool:
    n = csvio.import_products(shop, a.file)
    print(f"가져옴: {n}개")
    return True


def cmd_config(shop: Shop, a) -> bool:
    if a.key is None:
        print(f"locale\t{shop.settings.locale}")
        print(f"tax_display\t{shop.settings.tax_display}")
        return False
    if a.value is None:
        if a.key not in ("locale", "tax_display"):
            raise ValidationError(f"모르는 설정: {a.key}")
        print(getattr(shop.settings, a.key))
        return False
    shop.settings.set(a.key, a.value)
    print(f"{a.key}\t{a.value}")
    return True


# ====================================================================== 파서
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="shop", description="작은 온라인 가게 주문 관리")
    p.add_argument("--data", default=DEFAULT_DATA, help="데이터 파일 (기본 shop.json)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("product-add", help="상품 추가")
    s.add_argument("sku")
    s.add_argument("name")
    s.add_argument("category")
    s.add_argument("price")
    s.add_argument("--weight", default="0", help="무게(g)")
    s.add_argument("--tiers", default=None, help='수량 할인 "10:5,50:10"')
    s.add_argument("--inactive", action="store_true")
    s.set_defaults(func=cmd_product_add)

    s = sub.add_parser("variant-add", help="변형 추가")
    s.add_argument("product")
    s.add_argument("sku")
    s.add_argument("--price", default=None)
    s.add_argument("--weight", default=None)
    s.add_argument("--attr", action="append", default=[], help="KEY=VALUE (여러 번)")
    s.set_defaults(func=cmd_variant_add)

    sub.add_parser("products", help="판매 단위 목록").set_defaults(func=cmd_products)

    s = sub.add_parser("search", help="상품 찾기")
    s.add_argument("text")
    s.set_defaults(func=cmd_search)

    sub.add_parser("summary", help="상태별 주문 수와 합계 (운영용)").set_defaults(func=cmd_summary)

    s = sub.add_parser("variants", help="상품의 변형 목록")
    s.add_argument("product")
    s.set_defaults(func=cmd_variants)

    s = sub.add_parser("price-set", help="상품·변형 가격 바꾸기 (이미 만든 주문은 그대로)")
    s.add_argument("sku")
    s.add_argument("price")
    s.set_defaults(func=cmd_price_set)

    for name, active in (("activate", True), ("deactivate", False)):
        s = sub.add_parser(name, help="판매 재개" if active else "판매 중지")
        s.add_argument("sku")
        s.set_defaults(func=cmd_set_active(active))

    s = sub.add_parser("receive", help="입고")
    s.add_argument("sku")
    s.add_argument("qty", type=int)
    s.set_defaults(func=cmd_receive)

    sub.add_parser("stock", help="재고 목록").set_defaults(func=cmd_stock)

    s = sub.add_parser("low-stock", help="재고가 적은 판매 단위")
    s.add_argument("threshold", type=int)
    s.set_defaults(func=cmd_low_stock)

    s = sub.add_parser("tax-rate", help="카테고리 세율")
    s.add_argument("category")
    s.add_argument("rate")
    s.set_defaults(func=cmd_tax_rate)

    sub.add_parser("tax-rates", help="세율 표 (마지막 줄 * 는 기본 세율)").set_defaults(func=cmd_tax_rates)

    s = sub.add_parser("coupon-add", help="쿠폰 추가")
    s.add_argument("code")
    s.add_argument("kind", choices=["percent", "fixed", "category_percent", "free_shipping", "bundle"])
    s.add_argument("value", nargs="?", default="0")
    s.add_argument("--category", default=None)
    s.add_argument("--min", default="0", help="최소 주문 금액")
    s.add_argument("--stackable", action="store_true")
    s.add_argument("--expires", default=None, help="YYYY-MM-DD (그날까지 사용 가능)")
    s.add_argument("--max-uses", type=int, default=None)
    s.set_defaults(func=cmd_coupon_add)

    s = sub.add_parser("coupon-rm", help="쿠폰 삭제")
    s.add_argument("code")
    s.set_defaults(func=cmd_coupon_rm)

    sub.add_parser("coupons", help="쿠폰 목록").set_defaults(func=cmd_coupons)

    for name, func in (("quote", cmd_quote), ("order", cmd_order)):
        s = sub.add_parser(name, help="견적" if name == "quote" else "주문")
        s.add_argument("items", nargs="+", help="SKU:수량")
        s.add_argument("--region", default="domestic")
        s.add_argument("--coupon", action="append", default=[])
        if name == "order":
            s.add_argument("--customer", required=True)
            s.add_argument("--channel", default="web", help="web | store | phone")
        s.set_defaults(func=func)

    for name in ("pay", "ship", "cancel"):
        s = sub.add_parser(name)
        s.add_argument("id", type=int)
        s.set_defaults(func=_status_cmd(name))

    s = sub.add_parser("reprice", help="미결제 주문을 지금 가격으로 다시 계산")
    s.add_argument("id", type=int)
    s.set_defaults(func=cmd_reprice)

    s = sub.add_parser("refund", help="환불")
    s.add_argument("id", type=int)
    s.add_argument("items", nargs="*", help="SKU:수량")
    s.add_argument("--all", action="store_true", help="남은 것 전부(배송비 포함)")
    s.add_argument("--restock", action="store_true", help="출고된 상품을 재고로 되돌림")
    s.set_defaults(func=cmd_refund)

    s = sub.add_parser("expire-pending", help="오래된 미결제 주문 취소")
    s.add_argument("--hours", type=float, required=True)
    s.set_defaults(func=cmd_expire)

    s = sub.add_parser("show", help="주문 보기")
    s.add_argument("id", type=int)
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("history", help="주문 이벤트 기록")
    s.add_argument("id", type=int)
    s.set_defaults(func=cmd_history)

    s = sub.add_parser("orders", help="주문 목록")
    s.add_argument("--status", default=None)
    s.add_argument("--channel", default=None)
    s.set_defaults(func=cmd_orders)

    s = sub.add_parser("report", help="보고서")
    s.add_argument("kind", choices=["daily", "category", "top", "tax", "customers"])
    s.add_argument("args", nargs="*")
    s.add_argument("-n", type=int, default=5)
    s.add_argument("--from", dest="date_from", default=None)
    s.add_argument("--to", dest="date_to", default=None)
    s.add_argument("--channel", default=None, help="daily·category·top·tax: 그 판매 채널만")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("export", help="CSV 내보내기")
    s.add_argument("what", choices=["orders", "refunds", "products"])
    s.add_argument("file")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("import", help="CSV 가져오기")
    s.add_argument("what", choices=["products"])
    s.add_argument("file")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("config", help="설정 보기·바꾸기")
    s.add_argument("key", nargs="?")
    s.add_argument("value", nargs="?")
    s.set_defaults(func=cmd_config)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = Path(args.data)
    try:
        shop = storage.load(path, clock=_clock)
        if args.func(shop, args):
            storage.save(shop, path)
    except ShopError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    return 0
