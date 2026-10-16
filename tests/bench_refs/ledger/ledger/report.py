from decimal import ROUND_HALF_EVEN, Decimal

from ledger.book import balances
from ledger.errors import LedgerError
from ledger.money import fmt, precision


def _rate(src, dst, rates):
    if src == dst:
        return Decimal(1)
    if (src, dst) in rates:
        return Decimal(rates[(src, dst)])
    if (dst, src) in rates:
        return Decimal(1) / Decimal(rates[(dst, src)])
    raise LedgerError(f"환율 없음: {src}→{dst}")


def report(transactions, currency, rates, as_of=None, depth=None):
    quant = Decimal(1).scaleb(-precision(currency))
    lines, total = [], Decimal(0)
    for account, by_cur in balances(transactions, as_of=as_of, depth=depth).items():
        exact = sum((amount * _rate(cur, currency, rates) for cur, amount in by_cur.items()), Decimal(0))
        rounded = exact.quantize(quant, rounding=ROUND_HALF_EVEN)
        if rounded == 0:
            continue
        total += rounded
        lines.append(f"{account}\t{fmt(rounded, currency)}")
    lines.append(f"TOTAL\t{fmt(total, currency)}")
    return "\n".join(lines) + "\n"
