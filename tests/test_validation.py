from datetime import date
from decimal import Decimal

import pytest

from app.providers.base import ParsedBill
from app.validation import (check_account, check_model97, normalize_account, parse_amount,
                            parse_date, validate)


@pytest.mark.parametrize("text, value", [
    ("1.604,36", "1604.36"), ("1.604,36 din", "1604.36"), ("=5.249,00", "5249.00"),
    ("0,83", "0.83"), ("-0,01", "-0.01"), ("1.234.567,89", "1234567.89"),
])
def test_parse_amount(text, value):
    assert parse_amount(text) == Decimal(value)


@pytest.mark.parametrize("text", ["1604.36", "1,6", "abc", "1.60,36"])
def test_parse_amount_rejects(text):
    with pytest.raises(ValueError):
        parse_amount(text)


def test_parse_date():
    assert parse_date("15.10.2026") == parse_date("15.10.2026.") == date(2026, 10, 15)


@pytest.mark.parametrize("reference, ok", [
    ("95-300-021-0000001", True),
    ("953000210000001", True),
    ("96-300-021-0000001", False),
    ("95-300-021-0000002", False),
    ("95-300-021-000000A", False),
    ("1", False),
])
def test_model97(reference, ok):
    assert check_model97(reference) is ok


def test_account():
    assert normalize_account("205-506102-26") == "205000000050610226"
    assert check_account("205-506102-26")
    assert check_account("205000000050610226")
    assert not check_account("205-506102-27")
    assert not check_account("205-50610226")


def good_bill(**overrides) -> ParsedBill:
    values = dict(amount=Decimal("100.00"), due_date=date(2026, 10, 15), issue_date=date(2026, 10, 1),
                  reference="95-300-021-0000001", model="97", recipient_account="205000000050610226")
    sources = {s: {"amount": Decimal("100.00"), "reference": "953000210000001"} for s in ("email", "pdf", "qr")}
    bill = ParsedBill(provider="test", sources=sources, **values)
    for k, v in overrides.items():
        setattr(bill, k, v)
    return bill


def test_validate_ok():
    assert validate(good_bill(), Decimal("1000")) == []


@pytest.mark.parametrize("overrides, expected", [
    ({"amount": Decimal("0")}, "opsegu"),
    ({"amount": Decimal("5000")}, "opsegu"),
    ({"amount": None}, "Iznos nije"),
    ({"due_date": date(2026, 9, 1)}, "pre datuma izdavanja"),
    ({"reference": "96-300-021-0000001"}, "modelu 97"),
    ({"model": "00"}, "Nepoznat model"),
    ({"recipient_account": "205000000050610227"}, "kontrolni broj"),
])
def test_validate_problems(overrides, expected):
    problems = validate(good_bill(**overrides), Decimal("1000"))
    assert any(expected in p for p in problems), problems


def test_validate_source_mismatch_and_missing():
    bill = good_bill()
    bill.sources["qr"] = {}
    bill.sources["pdf"]["amount"] = Decimal("101.00")
    problems = validate(bill, Decimal("1000"))
    assert any("QR kod" in p and "nisu pročitani" in p for p in problems)
    assert any(p.startswith("Iznos se razlikuje") for p in problems)
