from decimal import Decimal

from imap_tools import MailMessage

import pytest

from app.db import connect, mark_reported_debts
from app.fetcher import process_message
from mts_fixture import BILL, PREVIOUS_BILL, build_eml

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


def store(conn, tmp_path, bill, n):
    msg = MailMessage.from_bytes(build_eml(bill, message_id=f"<test-{n}@mtsracun.rs>"))
    return process_message(conn, msg, tmp_path / "pdfs", MAX).bill_id


@pytest.mark.parametrize("order", [(PREVIOUS_BILL, BILL), (BILL, PREVIOUS_BILL)])
def test_debt_marks_previous_bill_unpaid(tmp_path, order):
    conn = connect(tmp_path / "test.db")
    ids = {b["reference"]: store(conn, tmp_path, b, i) for i, b in enumerate(order)}

    flagged = mark_reported_debts(conn)
    assert [(p["reference"], p["reporter_reference"]) for p in flagged] == [(PREVIOUS_BILL["reference"], BILL["reference"])]
    rows = {r["reference"]: r["reported_unpaid_by"] for r in conn.execute("SELECT * FROM bills")}
    assert rows == {PREVIOUS_BILL["reference"]: ids[BILL["reference"]], BILL["reference"]: None}
    assert mark_reported_debts(conn) == []  # already flagged


def test_debt_reverts_bill_marked_paid_before_next_issue(tmp_path):
    conn = connect(tmp_path / "test.db")
    store(conn, tmp_path, PREVIOUS_BILL, 1)
    conn.execute("UPDATE bills SET status = 'paid', paid_at = '2026-09-20T10:00:00'")
    store(conn, tmp_path, BILL, 2)
    mark_reported_debts(conn)
    row = conn.execute("SELECT * FROM bills WHERE reference = ?", (PREVIOUS_BILL["reference"],)).fetchone()
    assert (row["status"], row["paid_at"]) == ("unpaid", None)
    assert "prijavljuje da ovaj račun nije plaćen" in row["review_notes"]


def test_payment_after_next_issue_is_kept(tmp_path):
    conn = connect(tmp_path / "test.db")
    store(conn, tmp_path, PREVIOUS_BILL, 1)
    conn.execute("UPDATE bills SET status = 'paid', paid_at = '2026-10-03T10:00:00'")
    store(conn, tmp_path, BILL, 2)
    mark_reported_debts(conn)
    row = conn.execute("SELECT * FROM bills WHERE reference = ?", (PREVIOUS_BILL["reference"],)).fetchone()
    assert row["status"] == "paid" and row["reported_unpaid_by"]


def test_no_debt_or_gap_marks_nothing(tmp_path):
    conn = connect(tmp_path / "test.db")
    store(conn, tmp_path, {**PREVIOUS_BILL, "period_to": "30.08.2026"}, 1)  # not adjacent
    store(conn, tmp_path, BILL, 2)
    assert mark_reported_debts(conn) == []
    conn2 = connect(tmp_path / "test2.db")
    store(conn2, tmp_path, PREVIOUS_BILL, 1)
    store(conn2, tmp_path, {**BILL, "debt": "0,00"}, 2)
    assert mark_reported_debts(conn2) == []


def test_old_database_gets_new_column(tmp_path):
    path = tmp_path / "old.db"
    conn = connect(path)
    conn.execute("ALTER TABLE bills DROP COLUMN reported_unpaid_by")
    conn.close()
    columns = {r["name"] for r in connect(path).execute("PRAGMA table_info(bills)")}
    assert "reported_unpaid_by" in columns
