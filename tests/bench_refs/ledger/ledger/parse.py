import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

from ledger.errors import LedgerError
from ledger.money import parse_amount

_HEADER_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:\s+(.*))?$")
_SEGMENT_RE = re.compile(r"^\S+(?: \S+)*$")


@dataclass
class Posting:
    account: str
    amount: Decimal
    currency: str


@dataclass
class Transaction:
    date: dt.date
    description: str
    postings: list = field(default_factory=list)


def _account(text: str, lineno: int) -> str:
    parts = text.split(":")
    if not all(p and _SEGMENT_RE.match(p) for p in parts):
        raise LedgerError(f"계정 이름 오류: {text!r}", lineno)
    return text


def _posting(line: str, lineno: int):
    body = line.strip()
    m = re.match(r"^(.*?)(?:\t+|\s{2,})(.+)$", body)
    if not m:
        return _account(body, lineno), None
    account, rest = m.group(1), m.group(2).strip()
    parts = rest.split(" ")
    if len(parts) != 2:
        raise LedgerError(f"금액 형식 오류: {rest!r}", lineno)
    try:
        amount = parse_amount(parts[0], parts[1])
    except ValueError as e:
        raise LedgerError(str(e), lineno) from e
    return _account(account, lineno), (amount, parts[1])


def _finish(tx, raw, header_line):
    if len(raw) < 2:
        raise LedgerError("항목이 2개 이상이어야 합니다", header_line)
    missing = [i for i, (_, a) in enumerate(raw) if a is None]
    if len(missing) > 1:
        raise LedgerError("금액 생략은 거래당 하나까지", header_line)
    sums: dict[str, Decimal] = {}
    for _, a in raw:
        if a is not None:
            sums[a[1]] = sums.get(a[1], Decimal(0)) + a[0]
    if missing:
        if len(sums) != 1:
            raise LedgerError("생략 항목이 있는데 통화가 하나가 아님", header_line)
        (cur, total), = sums.items()
        raw[missing[0]] = (raw[missing[0]][0], (-total, cur))
        sums[cur] = Decimal(0)
    if any(v != 0 for v in sums.values()):
        raise LedgerError("통화별 합이 0 이 아님", header_line)
    tx.postings = [Posting(acc, a[0], a[1]) for acc, a in raw]
    return tx


def parse(text: str) -> list:
    out = []
    tx, raw, header_line = None, [], 0
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        if line[0] in " \t":
            if tx is None:
                raise LedgerError("거래 머리줄 앞의 항목", lineno)
            raw.append(_posting(line, lineno))
            continue
        m = _HEADER_RE.match(line.rstrip())
        if not m:
            raise LedgerError(f"형식 오류: {line!r}", lineno)
        if tx is not None:
            out.append(_finish(tx, raw, header_line))
        try:
            date = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError as e:
            raise LedgerError(f"날짜 오류: {e}", lineno) from e
        tx, raw, header_line = Transaction(date, (m.group(4) or "").strip()), [], lineno
    if tx is not None:
        out.append(_finish(tx, raw, header_line))
    return out
