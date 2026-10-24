"""Checks for parsed bills. Problems are returned as user-facing notes (Serbian)."""
import re
from datetime import date, datetime
from decimal import Decimal

SOURCE_NAMES = {"email": "mejl", "pdf": "PDF", "qr": "QR kod", "machine_line": "mašinski red"}
FIELD_NAMES = {
    "amount": "Iznos",
    "reference": "Poziv na broj",
    "recipient_account": "Račun primaoca",
    "due_date": "Rok za plaćanje",
}


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def parse_amount(text: str) -> Decimal:
    """Serbian format: `1.604,36` -> Decimal('1604.36')"""
    clean = text.strip().lstrip("=").removesuffix("din").strip()
    if not re.fullmatch(r"-?\d{1,3}(\.\d{3})*,\d{2}", clean):
        raise ValueError(f"Invalid amount: {text!r}")
    return Decimal(clean.replace(".", "").replace(",", "."))


def parse_date(text: str) -> date:
    """`15.10.2026` or `15.10.2026.`"""
    return datetime.strptime(text.strip().rstrip("."), "%d.%m.%Y").date()


def check_model97(reference: str) -> bool:
    """ISO 7064 mod 97-10: first two digits are the control number for the rest."""
    # shortcut: digits only; model 97 also allows letters (A=10...), add if a provider uses them
    d = digits(reference)
    if len(d) < 3 or len(d) != len(reference.replace("-", "").replace(" ", "")):
        return False
    return int(d[:2]) == 98 - int(d[2:] + "00") % 97


def normalize_account(text: str) -> str | None:
    """`205-506102-26` -> `205000000050610226` (bank 3 + account 13 + control 2)."""
    parts = text.strip().split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        bank, middle, control = parts
        if len(bank) == 3 and len(control) == 2 and len(middle) <= 13:
            return bank + middle.zfill(13) + control
    if len(text.strip()) == 18 and text.strip().isdigit():
        return text.strip()
    return None


def check_account(text: str) -> bool:
    n = normalize_account(text)
    return n is not None and int(n[16:]) == 98 - int(n[:16] + "00") % 97


def validate(bill, max_amount: Decimal) -> list[str]:
    problems = []
    if bill.amount is None:
        problems.append("Iznos nije pronađen.")
    elif not 0 < bill.amount <= max_amount:
        problems.append(f"Iznos {bill.amount} nije u dozvoljenom opsegu (0 - {max_amount}).")

    if bill.due_date is None:
        problems.append("Rok za plaćanje nije pronađen.")
    elif bill.issue_date and bill.due_date < bill.issue_date:
        problems.append("Rok za plaćanje je pre datuma izdavanja.")

    if not bill.reference:
        problems.append("Poziv na broj nije pronađen.")
    elif bill.model != "97":
        problems.append(f"Nepoznat model plaćanja: {bill.model}.")
    elif not check_model97(bill.reference):
        problems.append("Poziv na broj ne prolazi kontrolu po modelu 97.")

    if not bill.recipient_account:
        problems.append("Račun primaoca nije pronađen.")
    elif not check_account(bill.recipient_account):
        problems.append("Račun primaoca nema ispravan kontrolni broj.")

    for source in ("email", "pdf", "qr"):
        if not bill.sources.get(source):
            problems.append(f"Podaci iz izvora '{SOURCE_NAMES[source]}' nisu pročitani.")

    for field, label in FIELD_NAMES.items():
        values = {s: v[field] for s, v in bill.sources.items() if v.get(field) is not None}
        if len(set(values.values())) > 1:
            found = ", ".join(f"{SOURCE_NAMES[s]}: {v}" for s, v in values.items())
            problems.append(f"{label} se razlikuje između izvora ({found}).")

    return problems + bill.parse_errors
