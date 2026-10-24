from decimal import Decimal

from imap_tools import MailMessage

from app.db import connect
from app.fetcher import process_message
from mts_fixture import BILL, build_eml

MAX = Decimal("100000")


def test_stores_bill_once(tmp_path):
    conn = connect(tmp_path / "test.db")
    pdf_dir = tmp_path / "pdfs"
    msg = MailMessage.from_bytes(build_eml())

    result = process_message(conn, msg, pdf_dir, MAX)
    assert result.bill_id and result.verification == "verified"
    row = conn.execute("SELECT * FROM bills").fetchone()
    assert row["reference"] == "95-300-021-0000001"
    assert row["amount"] == "3683.46" and row["previous_debt"] == "2449.00"
    assert row["due_date"] == "2026-10-15"
    assert row["status"] == "unpaid"
    assert row["pdf_path"] == "INV95-300-021-0000001-postproc.pdf"
    assert (pdf_dir / "INV95-300-021-0000001-postproc.pdf").read_bytes().startswith(b"%PDF")

    # Same message again: skipped before parsing
    assert process_message(conn, msg, pdf_dir, MAX) is None
    # Same bill in a different message: kept out by the unique reference
    again = MailMessage.from_bytes(build_eml(message_id="<test-2@mtsracun.rs>"))
    assert process_message(conn, again, pdf_dir, MAX).bill_id is None
    assert conn.execute("SELECT COUNT(*) FROM bills").fetchone()[0] == 1


def test_needs_review_is_stored_with_notes(tmp_path):
    conn = connect(tmp_path / "test.db")
    msg = MailMessage.from_bytes(build_eml(pdf_bill={**BILL, "amount": "1,00"}))
    process_message(conn, msg, tmp_path / "pdfs", MAX)
    row = conn.execute("SELECT verification, review_notes FROM bills").fetchone()
    assert row["verification"] == "needs_review"
    assert "Iznos se razlikuje" in row["review_notes"]


def test_non_bill_is_ignored(tmp_path):
    conn = connect(tmp_path / "test.db")
    msg = MailMessage.from_bytes(build_eml(sender="news@example.com"))
    assert process_message(conn, msg, tmp_path / "pdfs", MAX) is None
