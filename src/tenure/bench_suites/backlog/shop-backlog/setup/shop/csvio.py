"""CSV 내보내기·가져오기.

로캘(settings.locale):
- default: 구분자 ',' , 소수점 '.'
- eu: 구분자 ';' , 소수점 ',' (유럽판 엑셀이 바로 열 수 있게). 가져오기도 같은 형식을 기대한다.

## 주문 내보내기 (export_orders)
주문 줄마다 한 행, 주문 번호 순(같은 주문 안에서는 줄 순서). 모든 상태의 주문을 내보낸다(취소 포함).
열: order_id, date, customer, status, sku, name, qty, unit_price, discount, net, tax
- date 는 주문 날짜(YYYY-MM-DD). 금액은 소수 둘째 자리. 배송비는 넣지 않는다.
- 표시 모드(tax_display)와 상관없이 언제나 세금 제외 금액이다(회계 프로그램이 읽는다).
- 첫 행은 머리글. UTF-8(BOM 없음), csv 모듈 기본 따옴표 규칙.

## 상품 가져오기 (import_products)
머리글: sku, name, category, price, weight_g [, tiers]. tiers 는 "10:5|50:10" (구간 사이 '|').
전부 아니면 전무: 한 행이라도 틀리면 아무것도 더하지 않고 ValidationError("N행: ...") (머리글이 1행).
이미 있는 SKU 나 파일 안에서 겹치는 SKU 도 오류.

## 환불 내보내기 (export_refunds)
환불마다 한 행, 환불 번호 순. 열: refund_id, order_id, date(환불한 날), items("SKU:수량|SKU:수량"), net, shipping,
tax, amount, reason.

## 상품 내보내기 (export_products)
열: sku, name, category, price, weight_g, tiers, active — 상품만(변형 제외), SKU 순.
"""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from .catalog import Catalog
from .errors import ShopError, ValidationError
from .money import fmt

ORDER_COLUMNS = ["order_id", "date", "customer", "status", "sku", "name", "qty", "unit_price", "discount", "net", "tax"]
REFUND_COLUMNS = ["refund_id", "order_id", "date", "items", "net", "shipping", "tax", "amount", "reason"]
PRODUCT_COLUMNS = ["sku", "name", "category", "price", "weight_g"]
PRODUCT_EXPORT_COLUMNS = ["sku", "name", "category", "price", "weight_g", "tiers", "active"]


def dialect_for(locale: str) -> tuple[str, str]:
    """(구분자, 소수점)."""
    return (";", ",") if locale == "eu" else (",", ".")


def _num(value: Decimal, decimal_sep: str) -> str:
    text = fmt(value)
    return text.replace(".", decimal_sep) if decimal_sep != "." else text


def export_orders(shop, path: str | Path) -> int:
    """행 수(머리글 제외)를 돌려준다."""
    delim, dec = dialect_for(shop.settings.locale)
    rows = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=delim)
        w.writerow(ORDER_COLUMNS)
        for order in shop.orders_list():
            for line in order.lines:
                w.writerow([order.id, order.created.date().isoformat(), order.customer, order.status, line.sku,
                            line.name, line.qty, _num(line.unit_price, dec), _num(line.discount, dec),
                            _num(line.net, dec), _num(line.tax, dec)])
                rows += 1
    return rows


def export_refunds(shop, path: str | Path) -> int:
    delim, dec = dialect_for(shop.settings.locale)
    refunds = sorted(shop.refunds, key=lambda r: r.id)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=delim)
        w.writerow(REFUND_COLUMNS)
        for r in refunds:
            items = "|".join(f"{sku}:{q}" for sku, q in r.items.items())
            w.writerow([r.id, r.order_id, r.created.date().isoformat(), items, _num(r.net, dec),
                        _num(r.shipping, dec), _num(r.tax, dec), _num(r.amount, dec), r.reason])
    return len(refunds)


def _tiers_text(tiers: list[tuple[int, Decimal]], dec: str) -> str:
    return "|".join(f"{q}:{format(p.normalize(), 'f').replace('.', dec)}" for q, p in tiers)


def export_products(shop, path: str | Path) -> int:
    delim, dec = dialect_for(shop.settings.locale)
    products = shop.catalog.products()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=delim)
        w.writerow(PRODUCT_EXPORT_COLUMNS)
        for p in products:
            w.writerow([p.sku, p.name, p.category, _num(p.price, dec), p.weight_g, _tiers_text(p.tiers, dec),
                        "yes" if p.active else "no"])
    return len(products)


def _parse_tiers_cell(text: str, dec: str) -> list[tuple[str, str]]:
    out = []
    for part in text.split("|"):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValidationError(f"수량 할인 구간 형식이 아닙니다: {part!r}")
        q, p = part.split(":", 1)
        out.append((q.strip(), p.strip().replace(dec, ".") if dec != "." else p.strip()))
    return out


def import_products(shop, path: str | Path) -> int:
    """가져온 상품 수를 돌려준다."""
    delim, dec = dialect_for(shop.settings.locale)
    try:
        with open(path, newline="", encoding="utf-8") as f:
            table = list(csv.reader(f, delimiter=delim))
    except OSError as e:
        raise ValidationError(f"파일을 읽을 수 없습니다: {e}") from None
    if not table:
        raise ValidationError("빈 파일입니다")
    header = [h.strip() for h in table[0]]
    if header not in (PRODUCT_COLUMNS, PRODUCT_COLUMNS + ["tiers"]):
        raise ValidationError(f"1행: 머리글은 {delim.join(PRODUCT_COLUMNS)}[{delim}tiers] 이어야 합니다")
    scratch = Catalog()
    pending = []
    for lineno, row in enumerate(table[1:], start=2):
        if not row or all(not c.strip() for c in row):
            continue
        if len(row) != len(header):
            raise ValidationError(f"{lineno}행: 열 수가 {len(header)}개가 아닙니다")
        rec = dict(zip(header, (c.strip() for c in row)))
        price = rec["price"].replace(dec, ".") if dec != "." else rec["price"]
        try:
            if rec["sku"] in shop.catalog:
                raise ValidationError(f"이미 있는 SKU: {rec['sku']}")
            tiers = _parse_tiers_cell(rec.get("tiers", ""), dec)
            scratch.add_product(rec["sku"], rec["name"], rec["category"], price, weight_g=rec["weight_g"] or 0,
                                tiers=tiers)
        except ShopError as e:
            raise ValidationError(f"{lineno}행: {e}") from None
        pending.append((rec["sku"], rec["name"], rec["category"], price, rec["weight_g"] or 0, tiers))
    for sku, name, category, price, weight, tiers in pending:
        shop.catalog.add_product(sku, name, category, price, weight_g=weight, tiers=tiers)
    return len(pending)
