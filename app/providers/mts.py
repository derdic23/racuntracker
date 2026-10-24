"""mts (Telekom Srbija) eRačun."""
import io
import re
from decimal import Decimal
from html.parser import HTMLParser

import pdfplumber
import pypdfium2
import zxingcpp
from imap_tools import MailMessage

from .. import ips
from ..validation import digits, normalize_account, parse_amount, parse_date
from .base import ParsedBill, Provider, normalize_text

SENDER = "eracun@mtsracun.rs"
DOMAIN = "mtsracun.rs"
RECIPIENT_NAME = "Telekom Srbija A.D."
PAYMENT_CODE = "189"

DATE = r"(\d{2}\.\d{2}\.\d{4})"
AMOUNT = r"(-?\d{1,3}(?:\.\d{3})*,\d{2})"
REFERENCE = r"(\d{2}-\d{3}-\d{3}-\d{7})"

# PDF text has two interleaved columns, so a value may be a few lines below its label
PDF_PATTERNS = {
    "bill_number": rf"Račun broj:.*?{REFERENCE}",
    "customer": r"Šifra korisnika/podračun:.*?(\d{5,}/\d+)",
    "issue_date": rf"Mesto i datum izdavanja:.*?{DATE}",
    "due_date": rf"Rok za plaćanje:.*?{DATE}",
    "period": rf"Za period: {DATE}\. - {DATE}\.",
    "amount": rf"UKUPNO ZA PLAĆANJE:\s*{AMOUNT}",
    "previous_debt": rf"DUG IZ PRETHODNOG PERIODA:\s*{AMOUNT}",
    "recipient_account": r"\b(\d{3}-\d{1,13}-\d{2})\b",
    "reference": rf"\b97 {REFERENCE}",
    # Machine-readable line: reference without control digits, account, amount in para
    "machine_line": r"\b(\d+)b (\d+)a (\d{11})c\b",
}

EMAIL_LABELS = {
    "iznos": "amount",
    "sifra korisnika/podracun": "customer",
    "tekuci racun za uplatu": "recipient_account",
    "poziv na broj": "reference",
    "model": "model",
    "rok za uplatu": "due_date",
}


class _BodyParser(HTMLParser):
    """Collects two-cell table rows (label, value) and the "PLATI RAČUN" link."""

    def __init__(self):
        super().__init__()
        self.rows, self.pairs = [], {}
        self.in_td = False
        self.link_href, self.link_text, self.payment_url = None, "", None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.rows.append([])
        elif tag == "td" and self.rows:
            self.rows[-1].append("")
            self.in_td = True
        elif tag == "a":
            self.link_href, self.link_text = dict(attrs).get("href"), ""

    def handle_endtag(self, tag):
        if tag == "tr" and self.rows:
            row = [" ".join(c.split()) for c in self.rows.pop()]
            if len(row) == 2 and row[0]:
                self.pairs[normalize_text(row[0])] = row[1]
        elif tag == "td":
            self.in_td = False
        elif tag == "a":
            if self.link_href and "plati" in normalize_text(self.link_text) and not self.payment_url:
                self.payment_url = self.link_href
            self.link_href = None

    def handle_data(self, data):
        if self.in_td and self.rows and self.rows[-1]:
            self.rows[-1][-1] += data
        if self.link_href is not None:
            self.link_text += data


def is_authentic(message: MailMessage) -> bool:
    """DKIM and SPF must pass for mtsracun.rs in the header added by Gmail."""
    results = message.headers.get("authentication-results", ())
    # Only the topmost header comes from Gmail; lower ones could be added by the sender
    if not results or not results[0].strip().lower().startswith("mx.google.com"):
        return False
    top = " ".join(results[0].split()).lower()  # unfold multi-line header
    dkim = re.findall(r"dkim=pass header\.i=@([\w.-]+)", top)
    spf = re.search(r"spf=pass .*?smtp\.mailfrom=\"?[^@\s\"]*@([\w.-]+)", top)
    is_mts = lambda d: d == DOMAIN or d.endswith("." + DOMAIN)
    return any(is_mts(d) for d in dkim) and bool(spf) and is_mts(spf.group(1))


def parse_email_body(html: str) -> tuple[dict, str | None]:
    parser = _BodyParser()
    parser.feed(html)
    fields = {EMAIL_LABELS[k]: v for k, v in parser.pairs.items() if k in EMAIL_LABELS}
    return fields, parser.payment_url


def parse_pdf_text(text: str) -> dict:
    found = {}
    for key, pattern in PDF_PATTERNS.items():
        m = re.search(pattern, text, re.DOTALL)
        if m:
            found[key] = m.groups() if len(m.groups()) > 1 else m.group(1)
    return found


def read_pdf(pdf_bytes: bytes) -> tuple[str, str | None]:
    """First page text and the IPS QR string, if any."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = pdf.pages[0].extract_text() or ""
    doc = pypdfium2.PdfDocument(pdf_bytes)
    try:
        image = doc[0].render(scale=2).to_pil()
    finally:
        doc.close()
    qr = next(
        (r.text for r in zxingcpp.read_barcodes(image)
         if r.format == zxingcpp.BarcodeFormat.QRCode and r.text.startswith("K:PR")),
        None,
    )
    return text, qr


class MtsProvider(Provider):
    name = "mts"
    senders = (SENDER,)

    def matches(self, message: MailMessage) -> bool:
        subject = normalize_text(message.subject)
        return (
            message.from_.lower() == SENDER
            and "eracun" in subject
            and "mts" in subject
            and any(a.content_type == "application/pdf" for a in message.attachments)
        )

    def parse(self, message: MailMessage) -> ParsedBill:
        bill = ParsedBill(provider=self.name, authentic=is_authentic(message))
        errors = bill.parse_errors

        def attempt(label, fn):
            try:
                return fn()
            except Exception as e:  # never fail silently: keep the bill, note the problem
                errors.append(f"{label}: {e}")
                return None

        email = attempt("Greška pri čitanju mejla", lambda: self._from_email(message, bill)) or {}
        pdf = next(a for a in message.attachments if a.content_type == "application/pdf")
        bill.pdf_filename, bill.pdf_bytes = pdf.filename, pdf.payload
        read = attempt("PDF nije moguće pročitati", lambda: read_pdf(pdf.payload))
        text, qr = read or ("", None)
        pdf_values = attempt("Greška pri čitanju PDF-a", lambda: self._from_pdf(text, bill)) or {}
        qr_values = (attempt("QR kod nije ispravan", lambda: self._from_qr(qr, bill)) or {}) if qr else {}

        bill.sources = {"email": email, "pdf": pdf_values, "qr": qr_values}
        machine = attempt("Greška u mašinskom redu", lambda: self._from_machine_line(text, bill))
        if machine:
            bill.sources["machine_line"] = machine

        # Machine-readable QR first, then PDF, then the e-mail body
        for key in ("amount", "recipient_account", "due_date"):
            value = next((s[key] for s in (qr_values, pdf_values, email) if s.get(key) is not None), None)
            setattr(bill, key, value)
        bill.reference = pdf_values.get("reference_text") or email.get("reference_text") or qr_values.get("reference")
        bill.model = qr_values.get("model") or email.get("model") or ("97" if pdf_values.get("reference") else None)
        bill.customer_id = bill.customer_id or email.get("customer_id")
        bill.sub_account = bill.sub_account or email.get("sub_account")

        if qr:
            bill.ips_string = qr if qr_values else None
        if not bill.ips_string:
            attempt("IPS QR nije moguće napraviti", lambda: setattr(bill, "ips_string", self._build_ips(bill)))
        return bill

    def _from_email(self, message: MailMessage, bill: ParsedBill) -> dict:
        fields, bill.payment_url = parse_email_body(message.html)
        values = {}
        if "amount" in fields:
            values["amount"] = parse_amount(fields["amount"])
        if "recipient_account" in fields:
            values["recipient_account"] = normalize_account(fields["recipient_account"])
        if "reference" in fields:
            values["reference"] = digits(fields["reference"])
            values["reference_text"] = fields["reference"]
        if "due_date" in fields:
            values["due_date"] = parse_date(fields["due_date"])
        if "model" in fields:
            values["model"] = fields["model"]
        if "customer" in fields:
            values["customer_id"], _, values["sub_account"] = fields["customer"].partition("/")
        return values

    def _from_pdf(self, text: str, bill: ParsedBill) -> dict:
        if not text:
            return {}
        found = parse_pdf_text(text)
        values = {}
        if "amount" in found:
            values["amount"] = parse_amount(found["amount"])
        if "recipient_account" in found:
            values["recipient_account"] = normalize_account(found["recipient_account"])
        if "reference" in found:
            values["reference"] = digits(found["reference"])
            values["reference_text"] = found["reference"]
        if "due_date" in found:
            values["due_date"] = parse_date(found["due_date"])
        if "issue_date" in found:
            bill.issue_date = parse_date(found["issue_date"])
        if "period" in found:
            bill.period_from, bill.period_to = map(parse_date, found["period"])
        if "previous_debt" in found:
            bill.previous_debt = parse_amount(found["previous_debt"]) or None
        bill.bill_number = found.get("bill_number")
        if "customer" in found:
            bill.customer_id, _, bill.sub_account = found["customer"].partition("/")
        return values

    def _from_qr(self, qr: str, bill: ParsedBill) -> dict:
        fields = ips.parse(qr)
        ro = fields.get("RO", "")
        return {
            "amount": ips.amount(fields),
            "recipient_account": normalize_account(fields["R"]),
            "model": ro[:2] or None,
            "reference": ro[2:] or None,
        }

    def _from_machine_line(self, text: str, bill: ParsedBill) -> dict | None:
        found = parse_pdf_text(text).get("machine_line")
        if not found:
            return None
        reference_body, _, para = found
        reference = bill.sources["pdf"].get("reference") or bill.sources["email"].get("reference")
        if reference and reference[2:] != reference_body:
            bill.parse_errors.append("Poziv na broj u mašinskom redu se ne slaže sa računom.")
        return {"amount": Decimal(int(para)) / 100}

    def _build_ips(self, bill: ParsedBill) -> str:
        purpose = "MTS Račun"
        if bill.period_to:
            purpose += f" {bill.period_to:%m/%Y}"
        if bill.customer_id:
            purpose += f" {bill.customer_id}/{bill.sub_account}"
        return ips.generate({
            "K": "PR", "V": "01", "C": "1",
            "R": bill.recipient_account or "",
            "N": RECIPIENT_NAME,
            "I": ips.format_amount(bill.amount) if bill.amount else "",
            "SF": PAYMENT_CODE,
            "S": purpose,
            "RO": f"97{digits(bill.reference)}" if bill.reference else "",
        })
