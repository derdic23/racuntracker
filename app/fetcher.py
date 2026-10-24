"""Finds new bill e-mails in Gmail (IMAP) and stores them."""
import re
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from imap_tools import OR, MailBox, MailMessage
from imap_tools.errors import MailboxFolderSelectError

from .db import has_message, insert_bill
from .providers import ParsedBill, all_senders, find_provider
from .validation import validate

GMAIL_IMAP = "imap.gmail.com"


@dataclass
class Result:
    bill: ParsedBill
    verification: str
    notes: list[str]
    bill_id: int | None  # None: already stored (same reference)


def check(bill: ParsedBill, max_amount: Decimal) -> tuple[str, list[str]]:
    notes = validate(bill, max_amount)
    if not bill.authentic:
        return "suspicious", ["Mejl nije prošao DKIM/SPF proveru pošiljaoca."] + notes
    return ("needs_review" if notes else "verified"), notes


def message_id(message: MailMessage) -> str:
    return (message.headers.get("message-id") or ("",))[0].strip()


def process_message(conn: sqlite3.Connection, message: MailMessage, pdf_dir: Path, max_amount: Decimal) -> Result | None:
    """Parse and store one message. None if it is not a bill or was already processed."""
    mid = message_id(message)
    if not mid or has_message(conn, mid):
        return None
    provider = find_provider(message)
    if provider is None:
        return None
    bill = provider.parse(message)
    verification, notes = check(bill, max_amount)
    pdf_path = pdf_dir / re.sub(r"[^\w.-]", "_", Path(bill.pdf_filename or "bill.pdf").name)
    with conn:  # file is written only for a new row; a failed write rolls the row back
        bill_id = insert_bill(conn, bill, verification=verification, notes=notes, pdf_path=pdf_path.name, message_id=mid)
        if bill_id and bill.pdf_bytes:
            pdf_dir.mkdir(parents=True, exist_ok=True)
            pdf_path.write_bytes(bill.pdf_bytes)
    return Result(bill, verification, notes, bill_id)


def _folders(mailbox: MailBox, label: str) -> list[tuple[str, bool]]:
    """(folder, filter_by_sender). The label holds only bills; All Mail and Spam are a fallback."""
    folders = mailbox.folder.list()
    # Found by flag because Gmail localizes names; All Mail also covers archived mail, unlike INBOX
    all_mail = next((f.name for f in folders if "\\All" in f.flags), "INBOX")
    spam = next((f.name for f in folders if "\\Junk" in f.flags), None)
    return [(label, False), (all_mail, True)] + ([(spam, True)] if spam else [])


def fetch(conn: sqlite3.Connection, address: str, password: str, label: str, pdf_dir: Path, max_amount: Decimal) -> list[Result]:
    results = []
    with MailBox(GMAIL_IMAP).login(address, password) as mailbox:
        for folder, by_sender in _folders(mailbox, label):
            try:
                mailbox.folder.set(folder, readonly=True)
            except MailboxFolderSelectError:
                print(f"Folder '{folder}' ne postoji, preskačem.")
                continue
            criteria = OR(from_=all_senders()) if by_sender else "ALL"
            # shortcut: downloads every matching message each run; add a date filter if the mailbox gets large
            for message in mailbox.fetch(criteria, mark_seen=False):
                result = process_message(conn, message, pdf_dir, max_amount)
                if result:
                    results.append(result)
    return results
