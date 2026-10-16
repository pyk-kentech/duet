import datetime as dt
from decimal import Decimal as D

import pytest

from ledger import LedgerError, balances, parse, report

J1 = """; sample
2026-01-03 Coffee shop
    expenses:food        4.50 USD
    assets:cash
2026-01-04 Salary
    assets:bank      1,200.00 USD
    income:salary   (1,200.00) USD

2026-01-10 Groceries
    expenses:food      30 USD
    expenses:eating out   12.25 USD
\tassets:bank
"""

J2 = """2026-02-01 Trip
    expenses:a    1.00 EUR
    expenses:b    1.00 EUR
    assets:cash  -2.00 EUR
2026-02-02 Tokyo
    expenses:hotel   12,340 JPY
    assets:card   -12,340 JPY
"""


def test_parse_structure():
    txs = parse(J1)
    assert [t.date for t in txs] == [dt.date(2026, 1, 3), dt.date(2026, 1, 4), dt.date(2026, 1, 10)]
    assert [t.description for t in txs] == ["Coffee shop", "Salary", "Groceries"]
    cash = txs[0].postings[1]
    assert (cash.account, cash.amount, cash.currency) == ("assets:cash", D("-4.50"), "USD")
    assert isinstance(cash.amount, D)
    assert txs[1].postings[1].amount == D("-1200.00")
    assert [p.account for p in txs[2].postings] == ["expenses:food", "expenses:eating out", "assets:bank"]
    assert txs[2].postings[2].amount == D("-42.25")


def test_empty_description_and_comments():
    txs = parse("  ; indented comment\n2026-05-01\n    a  1 USD\n    b\n")
    assert txs[0].description == "" and txs[0].postings[1].amount == D("-1")


def test_single_space_is_part_of_account_name():
    # 구분은 공백 2개 이상 또는 탭. 공백 하나는 계정 이름의 일부다
    txs = parse("2026-01-01 X\n    expenses:food 4.50 USD\n    assets:cash  -4.50 USD\n")
    p = txs[0].postings[0]
    assert p.account == "expenses:food 4.50 USD" and p.amount == D("4.50") and p.currency == "USD"


def test_balances_basic():
    b = balances(parse(J1))
    assert list(b) == ["assets:bank", "assets:cash", "expenses:eating out", "expenses:food", "income:salary"]
    assert b["assets:bank"] == {"USD": D("1157.75")}
    assert b["expenses:food"] == {"USD": D("34.50")}
    assert b["income:salary"] == {"USD": D("-1200")}


def test_balances_as_of_inclusive_and_depth():
    b = balances(parse(J1), as_of=dt.date(2026, 1, 4))
    assert b == {"assets:bank": {"USD": D("1200")}, "assets:cash": {"USD": D("-4.50")},
                 "expenses:food": {"USD": D("4.50")}, "income:salary": {"USD": D("-1200")}}
    d1 = balances(parse(J1), depth=1)
    assert d1 == {"assets": {"USD": D("1153.25")}, "expenses": {"USD": D("46.75")}, "income": {"USD": D("-1200")}}
    with pytest.raises(ValueError):
        balances(parse(J1), depth=0)


def test_balances_drop_zero():
    txs = parse("2026-01-01 a\n    x  5 USD\n    y\n2026-01-02 b\n    y  5 USD\n    x\n")
    assert balances(txs) == {}


def test_report_single_currency():
    assert report(parse(J1), "USD", {}) == (
        "assets:bank\t1,157.75\nassets:cash\t-4.50\nexpenses:eating out\t12.25\n"
        "expenses:food\t34.50\nincome:salary\t-1,200.00\nTOTAL\t0.00\n")


def test_report_total_is_sum_of_rounded_lines():
    rates = {("EUR", "USD"): D("1.125"), ("USD", "JPY"): D("150")}
    assert report(parse(J2), "USD", rates) == (
        "assets:card\t-82.27\nassets:cash\t-2.25\nexpenses:a\t1.12\nexpenses:b\t1.12\n"
        "expenses:hotel\t82.27\nTOTAL\t-0.01\n")


def test_report_half_even_and_inverse_rate():
    rates = {("EUR", "USD"): D("1.125"), ("EUR", "JPY"): D("160")}
    assert report(parse(J2), "EUR", rates) == (
        "assets:card\t-77.12\nassets:cash\t-2.00\nexpenses:a\t1.00\nexpenses:b\t1.00\n"
        "expenses:hotel\t77.12\nTOTAL\t0.00\n")


def test_report_zero_decimal_currency():
    rates = {("EUR", "JPY"): D("160")}
    assert report(parse(J2), "JPY", rates) == (
        "assets:card\t-12,340\nassets:cash\t-320\nexpenses:a\t160\nexpenses:b\t160\n"
        "expenses:hotel\t12,340\nTOTAL\t0\n")


def test_report_drops_accounts_rounding_to_zero():
    txs = parse("2026-03-01 Tiny\n    expenses:tiny   0.01 USD\n    assets:cash\n")
    assert report(txs, "JPY", {("USD", "JPY"): D("0.4")}) == "TOTAL\t0\n"


def test_report_per_account_rounding_not_per_posting():
    txs = parse("2026-01-01 a\n    x  0.01 EUR\n    z\n2026-01-02 b\n    x  0.01 EUR\n    z\n"
                "2026-01-03 c\n    x  0.01 EUR\n    z\n")
    out = report(txs, "USD", {("EUR", "USD"): D("1.5")})
    assert out.splitlines()[0] == "x\t0.04"          # 0.03 × 1.5 = 0.045 → 0.04 (포스팅마다 반올림하면 0.06)


def test_report_missing_rate():
    with pytest.raises(LedgerError) as e:
        report(parse(J2), "JPY", {("EUR", "USD"): D("1.1")})
    assert e.value.lineno is None


@pytest.mark.parametrize("text,lineno", [
    ("2026-02-30 Bad\n    a  1.00 USD\n    b\n", 1),
    ("2026-01-01 X\n    a  1.00 USD\n    b  -0.99 USD\n", 1),
    ("; c\n\n2026-01-01 X\n    a  1.00 USD\n    b  -0.99 USD\n", 3),
    ("2026-01-01 ok\n    a  1 USD\n    b\n2026-01-02 X\n    a\n    b\n", 4),
    ("2026-01-01 X\n    a  1.00 USD\n    b  1.00 EUR\n    c\n", 1),
    ("2026-01-01 X\n    a  1.00 USD\n", 1),
    ("    a  1.00 USD\n2026-01-01 X\n", 1),
    ("2026-01-01 X\n    a  1,2345.00 USD\n    b\n", 2),
    ("2026-01-01 X\n    a  12,34 USD\n    b\n", 2),
    ("2026-01-01 X\n    a  4.505 USD\n    b\n", 2),
    ("2026-01-01 X\n    a  10.5 JPY\n    b\n", 2),
    ("2026-01-01 X\n    a  1.00 usd\n    b\n", 2),
    ("2026-01-01 X\n    a  -(1.00) USD\n    b\n", 2),
    ("2026-01-01 X\n    a  1.00\n    b\n", 2),
    ("2026/01/01 X\n    a  1 USD\n    b\n", 1),
    ("2026-01-01 X\n    a::b  1 USD\n    c\n", 2),
])
def test_errors(text, lineno):
    with pytest.raises(LedgerError) as e:
        parse(text)
    assert e.value.lineno == lineno
    assert isinstance(e.value, ValueError)


def test_amount_formats():
    txs = parse("2026-01-01 X\n    a  1,234,567.8 USD\n    b  -1234567.80 USD\n"
                "2026-01-02 Y\n    a  (5) KRW\n    b  5 KRW\n")
    assert txs[0].postings[0].amount == D("1234567.8")
    assert txs[1].postings[0].amount == D("-5")
