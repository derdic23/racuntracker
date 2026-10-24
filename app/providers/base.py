import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from imap_tools import MailMessage


@dataclass
class ParsedBill:
    provider: str
    customer_id: str | None = None
    sub_account: str | None = None
    bill_number: str | None = None
    reference: str | None = None  # poziv na broj, unique key of a bill
    model: str | None = None
    recipient_account: str | None = None
    amount: Decimal | None = None
    previous_debt: Decimal | None = None
    issue_date: date | None = None
    due_date: date | None = None
    period_from: date | None = None
    period_to: date | None = None
    ips_string: str | None = None
    payment_url: str | None = None
    pdf_filename: str | None = None
    pdf_bytes: bytes | None = field(default=None, repr=False)
    authentic: bool = False
    # Normalized values per source ("email", "pdf", "qr", ...) compared by validation
    sources: dict[str, dict] = field(default_factory=dict)
    parse_errors: list[str] = field(default_factory=list)


class Provider:
    name: str
    senders: tuple[str, ...]

    def matches(self, message: MailMessage) -> bool:
        raise NotImplementedError

    def parse(self, message: MailMessage) -> ParsedBill:
        raise NotImplementedError

    def payment_url(self, bill: ParsedBill) -> str | None:
        return bill.payment_url


def normalize_text(text: str) -> str:
    """Lowercase, no diacritics: `eRačun Đ` -> `eracun dj`."""
    text = text.lower().replace("đ", "dj")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
