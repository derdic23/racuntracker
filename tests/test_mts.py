from datetime import date
from decimal import Decimal

from imap_tools import MailMessage

from app import ips
from app.fetcher import check
from app.providers import find_provider
from app.providers.mts import MtsProvider, is_authentic
from mts_fixture import BILL, build_eml

MAX = Decimal("100000")


def message(**kwargs) -> MailMessage:
    return MailMessage.from_bytes(build_eml(**kwargs))


def test_parses_all_fields():
    msg = message()
    assert isinstance(find_provider(msg), MtsProvider)
    bill = MtsProvider().parse(msg)
    assert bill.authentic
    assert (bill.customer_id, bill.sub_account) == ("12345678", "2")
    assert bill.reference == bill.bill_number == "95-300-021-0000001"
    assert bill.model == "97"
    assert bill.recipient_account == "205000000050610226"
    assert bill.amount == Decimal("3683.46")
    assert bill.previous_debt == Decimal("2449.00")
    assert bill.issue_date == date(2026, 10, 1)
    assert bill.due_date == date(2026, 10, 15)
    assert (bill.period_from, bill.period_to) == (date(2026, 9, 1), date(2026, 9, 30))
    assert bill.payment_url == "https://mts.rs/placanje-racuna?t=TESTTOKEN"
    assert ips.parse(bill.ips_string)["RO"] == "97953000210000001"
    assert set(bill.sources) == {"email", "pdf", "qr", "machine_line"}
    assert check(bill, MAX) == ("verified", [])


def test_not_matching_other_sender_or_subject():
    assert find_provider(message(sender="eracun@example.com")) is None
    assert find_provider(message(subject="Novi mts paketi")) is None
    assert find_provider(message(subject="ERACUN ZA MTS USLUGE")) is not None


def test_failed_dkim_is_suspicious():
    bill = MtsProvider().parse(message(auth="mx.google.com; dkim=fail header.i=@mtsracun.rs; spf=pass smtp.mailfrom=a@mtsracun.rs"))
    assert check(bill, MAX)[0] == "suspicious"


def test_auth_header_not_from_gmail_is_ignored():
    # The sender can add its own Authentication-Results; only Gmail's (topmost) counts
    assert not is_authentic(message(auth="evil.example; dkim=pass header.i=@mtsracun.rs; spf=pass smtp.mailfrom=a@mtsracun.rs"))


def test_amount_mismatch_needs_review():
    bill = MtsProvider().parse(message(pdf_bill={**BILL, "amount": "3.683,47"}))
    verification, notes = check(bill, MAX)
    assert verification == "needs_review"
    assert any(n.startswith("Iznos se razlikuje") for n in notes)


def test_missing_qr_needs_review_and_builds_ips():
    bill = MtsProvider().parse(message(qr=None))
    verification, notes = check(bill, MAX)
    assert verification == "needs_review"
    assert any("QR kod" in n for n in notes)
    fields = ips.parse(bill.ips_string)
    assert ips.amount(fields) == Decimal("3683.46")
    assert fields["R"] == "205000000050610226"
    assert fields["RO"] == "97953000210000001"


def test_broken_pdf_keeps_bill():
    bill = MtsProvider().parse(message(pdf=b"not a pdf"))
    verification, notes = check(bill, MAX)
    assert verification == "needs_review"
    assert any(n.startswith("PDF nije moguće pročitati") for n in notes)
    assert bill.amount == Decimal("3683.46")  # still known from the e-mail body
    assert bill.pdf_bytes == b"not a pdf"
