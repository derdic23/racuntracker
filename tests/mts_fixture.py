"""Builds anonymized mts eRačun e-mails (HTML body + PDF with text layer and IPS QR).

All personal data is made up. The PDF text follows the layout of a real bill's first page.
"""
import io
import zlib
from email.message import EmailMessage
from pathlib import Path

import qrcode

FIXTURES = Path(__file__).parent / "fixtures"

# Fake bill. Reference passes model 97: 98 - int("300021000000100") % 97 == 95
BILL = {
    "name": "PETAR PETROVIĆ",
    "street": "GLAVNA 1",
    "city": "11000 BEOGRAD",
    "customer": "12345678/2",
    "reference": "95-300-021-0000001",
    "amount": "3.683,46",
    "debt": "2.449,00",
    "issue_date": "01.10.2026",
    "due_date": "15.10.2026",
}

AUTH_OK = (
    "mx.google.com; dkim=pass header.i=@mtsracun.rs header.s=tpc header.b=TEST; "
    "spf=pass (google.com: domain of bounces@em1.mtsracun.rs designates 192.0.2.1 as permitted sender) "
    'smtp.mailfrom="bounces@em1.mtsracun.rs"; dmarc=pass header.from=mtsracun.rs'
)


def ips_string(b: dict) -> str:
    amount = b["amount"].replace(".", "")
    customer_id = b["customer"].split("/")[0]
    return (
        "K:PR|V:01|C:1|R:205000000050610226|N:Telekom Srbija A.D.\r\nZorana Žunkovića 23\r\nBeograd"
        f"|I:RSD{amount}|P:{b['name']}\r\n{b['street']}\r\n{b['city']}|SF:189"
        f"|S:MTS Račun 09/2026 {b['customer']}|RO:97{b['reference'].replace('-', '')}"
    )


def pdf_lines(b: dict) -> list[str]:
    amount_para = b["amount"].replace(".", "").replace(",", "").zfill(11)
    ref_body = b["reference"].replace("-", "")[2:]
    customer_id = b["customer"].split("/")[0]
    return [
        "Telekom Srbija a.d. Beograd PIB: 100002887",
        "Zorana Žunkovića 23, Beograd",
        "Septembar, 2026. godine",
        "Račun broj: Kontakt:",
        f"{b['reference']} Info centar i prijava smetnji:",
        "Šifra korisnika/podračun: 0800/100100",
        b["name"],
        f"{b['customer']} supernova@telekom.rs",
        f"Mesto i datum izdavanja: www.mts.rs {b['street']}",
        f"Beograd, {b['issue_date']}.",
        "Datum prometa: BEOGRAD",
        "30.09.2026.",
        "Rok za plaćanje:",
        f"{b['due_date']}.",
        "Za period: 01.09.2026. - 30.09.2026.",
        "1. Naknada 3.140,52 83,33 3.057,19 20% 611,44 3.668,63",
        "3. Zatezna kamata * 13,84",
        f"UKUPNO ZA PLAĆANJE: {b['amount']}",
        f"Vaše dugovanje na dan {b['issue_date']} iznosi {b['debt']}. Da biste izbegli",
        f"izmirite svoje dugovanje. DUG IZ PRETHODNOG PERIODA: {b['debt']}",
        f"Račun za telekom usluge: 01.09.2026.-30.09.2026. Šifra korisnika: {customer_id}",
        f"Nalogodavac: 205-506102-26 ={b['amount']}",
        b["name"],
        f"{b['street']} 97 {b['reference']} 97 {b['reference']}",
        "Primalac: Nalogodavac:",
        f"Telekom Srbija A.D. {b['name']}",
        f"{ref_body}b 0050610226a {amount_para}c 20500000b 13a",
        "NBS IPS QR kod",
    ]


# Standard PDF fonts have no č/ć/đ, so map them via an encoding Differences array
EXTRA_GLYPHS = {"Š": "Scaron", "š": "scaron", "Ž": "Zcaron", "ž": "zcaron", "Č": "Ccaron",
                "č": "ccaron", "Ć": "Cacute", "ć": "cacute", "Đ": "Dcroat", "đ": "dcroat"}
CODES = {ch: 128 + i for i, ch in enumerate(EXTRA_GLYPHS)}


def _pdf_text(line: str) -> bytes:
    out = bytearray()
    for ch in line:
        if ch in CODES:
            out.append(CODES[ch])
        elif ch in "()\\":
            out += b"\\" + ch.encode()
        else:
            out += ch.encode("ascii")
    return bytes(out)


def build_pdf(lines: list[str], qr: str | None) -> bytes:
    content = b"BT /F1 8 Tf 40 800 Td 11 TL\n"
    content += b"".join(b"(" + _pdf_text(line) + b") '\n" for line in lines) + b"ET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> /XObject << /Im1 6 0 R >> >> >>",
    ]
    image = b""
    if qr:
        img = qrcode.make(qr, error_correction=qrcode.constants.ERROR_CORRECT_M).get_image().convert("L")
        image = zlib.compress(img.tobytes())
        content += b"q 160 0 0 160 400 40 cm /Im1 Do Q\n"
        size = b"/Width %d /Height %d" % img.size
    else:
        image, size = zlib.compress(b"\xff"), b"/Width 1 /Height 1"
    differences = b" ".join(b"/" + g.encode() for g in EXTRA_GLYPHS.values())
    objects += [
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding << /Type /Encoding /BaseEncoding /WinAnsiEncoding /Differences [128 " + differences + b"] >> >>",
        b"<< /Type /XObject /Subtype /Image " + size + b" /ColorSpace /DeviceGray /BitsPerComponent 8 "
        b"/Filter /FlateDecode /Length %d >>\nstream\n" % len(image) + image + b"\nendstream",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    out.write(b"".join(b"%010d 00000 n \n" % o for o in offsets))
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref))
    return out.getvalue()


def build_eml(bill: dict | None = None, *, pdf_bill: dict | None = None, qr: str | None = "default",
              auth: str = AUTH_OK, sender: str = "eracun@mtsracun.rs",
              subject: str = "eRačun za mts usluge", message_id: str = "<test-1@mtsracun.rs>",
              pdf: bytes | None = None) -> bytes:
    """`pdf_bill` lets the PDF disagree with the e-mail body; `qr=None` leaves the QR out."""
    b = bill or BILL
    pb = pdf_bill or b
    html = (FIXTURES / "mts_body.html").read_text().format(
        amount=b["amount"], customer=b["customer"], reference=b["reference"], due_date=b["due_date"])
    msg = EmailMessage()
    msg["Authentication-Results"] = auth
    msg["From"] = f"mts račun <{sender}>"
    msg["To"] = "korisnik@example.com"
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg.set_content("Vaš račun je u prilogu.")
    msg.add_alternative(html, subtype="html")
    pdf = pdf or build_pdf(pdf_lines(pb), ips_string(pb) if qr == "default" else qr)
    msg.add_attachment(pdf, maintype="application", subtype="pdf",
                       filename=f"INV{pb['reference']}-postproc.pdf")
    return msg.as_bytes()
