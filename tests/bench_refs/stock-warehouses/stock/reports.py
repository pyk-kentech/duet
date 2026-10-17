"""창고별 보고."""


def low_stock_by_warehouse(inv, threshold):
    out = []
    for w in inv.warehouses():
        for item in inv.items():
            q = inv.on_hand(item.sku, w.code)
            if q <= threshold:
                out.append((w.code, item.sku, q))
    return out


def movements_summary(inv, start, end):
    acc: dict[str, dict[str, int]] = {}
    for m in inv.history():
        if start <= m.ts < end:
            k = acc.setdefault(m.warehouse, {})
            k[m.kind] = k.get(m.kind, 0) + m.qty
    return {w: dict(sorted(acc[w].items())) for w in sorted(acc)}
