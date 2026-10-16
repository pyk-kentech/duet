from decimal import Decimal


def balances(transactions, as_of=None, depth=None):
    if depth is not None and depth < 1:
        raise ValueError("depth 는 1 이상")
    acc: dict[str, dict[str, Decimal]] = {}
    for tx in transactions:
        if as_of is not None and tx.date > as_of:
            continue
        for p in tx.postings:
            name = ":".join(p.account.split(":")[:depth]) if depth else p.account
            cur = acc.setdefault(name, {})
            cur[p.currency] = cur.get(p.currency, Decimal(0)) + p.amount
    out = {}
    for name in sorted(acc):
        nonzero = {c: v for c, v in sorted(acc[name].items()) if v != 0}
        if nonzero:
            out[name] = nonzero
    return out
