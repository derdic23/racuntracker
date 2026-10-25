import re
from decimal import Decimal

import pypdfium2 as pdfium
import pytest
from imap_tools import MailMessage

from app import create_app
from app.db import connect, mark_reported_debts
from app.fetcher import process_message
from mts_fixture import BILL, PREVIOUS_BILL, build_eml

PASSWORD = "test-lozinka"


@pytest.fixture
def app(tmp_path):
    db_path, pdf_dir = tmp_path / "test.db", tmp_path / "pdfs"
    conn = connect(db_path)
    for bill, mid in ((PREVIOUS_BILL, "<prev@mtsracun.rs>"), (BILL, "<cur@mtsracun.rs>")):
        process_message(conn, MailMessage.from_bytes(build_eml(bill, message_id=mid)), pdf_dir, Decimal("100000"))
    mark_reported_debts(conn)
    conn.close()
    return create_app(SECRET_KEY="test", APP_PASSWORD=PASSWORD, DB_PATH=db_path, PDF_DIR=pdf_dir)


def csrf(client, path="/prijava") -> str:
    return re.search(r'name="csrf" value="([^"]+)"', client.get(path).get_data(as_text=True))[1]


@pytest.fixture
def client(app):
    c = app.test_client()
    assert c.post("/prijava", data={"password": PASSWORD, "csrf": csrf(c)}).status_code == 302
    return c


def bill_id(app, reference: str) -> int:
    conn = connect(app.config["DB_PATH"])
    try:
        return conn.execute("SELECT id FROM bills WHERE reference = ?", (reference,)).fetchone()[0]
    finally:
        conn.close()


def test_requires_login(app):
    c = app.test_client()
    for path in ("/", "/racun/1", "/racun/1/qr.png", "/racun/1/pdf", "/kalendar", "/uputstvo", "/podesavanja/"):
        r = c.get(path)
        assert r.status_code == 302 and r.location.endswith("/prijava")


def test_wrong_password_and_missing_csrf(app):
    c = app.test_client()
    r = c.post("/prijava", data={"password": "pogresno", "csrf": csrf(c)})
    assert r.status_code == 401 and "Pogrešna lozinka" in r.get_data(as_text=True)
    assert c.post("/prijava", data={"password": PASSWORD}).status_code == 400
    assert c.get("/").status_code == 302


def test_refuses_to_start_without_secrets(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(SECRET_KEY="", APP_PASSWORD="x", DB_PATH=tmp_path / "t.db")


def test_list_shows_unpaid_with_debt_warning(client):
    html = client.get("/").get_data(as_text=True)
    assert "3.683,46 din" in html and "2.449,00 din" in html
    assert "Septembar 2026" in html and "Avgust 2026" in html
    assert "mts: nije plaćen" in html  # previous bill reported unpaid by the later one
    assert html.index("Septembar 2026") < html.index("Avgust 2026")  # newest first


def test_detail_qr_and_pdf(app, client):
    bid = bill_id(app, BILL["reference"])
    html = client.get(f"/racun/{bid}").get_data(as_text=True)
    assert "95-300-021-0000001" in html and "Dug iz prethodnog perioda: 2.449,00 din" in html
    assert "Plati na mts sajtu" in html and "Štampaj račun" in html and "Otvori PDF" in html
    assert "205-506102-26" in html

    qr = client.get(f"/racun/{bid}/qr.png")
    assert qr.mimetype == "image/png" and qr.data.startswith(b"\x89PNG")
    assert "attachment" not in qr.headers.get("Content-Disposition", "")
    assert "attachment" in client.get(f"/racun/{bid}/qr.png?preuzmi=1").headers["Content-Disposition"]

    pdf = client.get(f"/racun/{bid}/pdf")
    assert pdf.mimetype == "application/pdf" and pdf.data.startswith(b"%PDF")
    assert len(pdfium.PdfDocument(pdf.data)) == 1  # only the bill page
    assert "attachment" not in pdf.headers.get("Content-Disposition", "")
    assert client.get("/racun/999").status_code == 404


def test_mark_paid_and_back(app, client):
    bid = bill_id(app, BILL["reference"])
    token = csrf(client, f"/racun/{bid}")
    assert client.post(f"/racun/{bid}/placeno").status_code == 400  # no CSRF token
    client.post(f"/racun/{bid}/placeno", data={"csrf": token})
    html = client.get(f"/racun/{bid}").get_data(as_text=True)
    assert "plaćeno" in html and "Vrati na neplaćeno" in html
    client.post(f"/racun/{bid}/placeno", data={"csrf": token})
    assert "Obeleži kao plaćeno" in client.get(f"/racun/{bid}").get_data(as_text=True)


def test_remember_me(app):
    def login(**extra):
        c = app.test_client()
        r = c.post("/prijava", data={"password": PASSWORD, "csrf": csrf(c), **extra})
        return r.headers["Set-Cookie"]
    assert "Expires=" in login(remember="on")
    assert "Expires=" not in login()  # browser-session cookie


def test_logout(client):
    token = csrf(client, "/")
    client.post("/odjava", data={"csrf": token})
    assert client.get("/").status_code == 302


def test_pdf_shows_only_first_page(app, client):
    doc = pdfium.PdfDocument.new()
    for _ in range(3):
        doc.new_page(595, 842)
    doc.save(app.config["PDF_DIR"] / "three-pages.pdf")
    bid = bill_id(app, BILL["reference"])
    conn = connect(app.config["DB_PATH"])
    with conn:
        conn.execute("UPDATE bills SET pdf_path = 'three-pages.pdf' WHERE id = ?", (bid,))
    conn.close()
    assert len(pdfium.PdfDocument(client.get(f"/racun/{bid}/pdf").data)) == 1
    assert len(pdfium.PdfDocument(client.get(f"/racun/{bid}/pdf?ceo=1").data)) == 3
    assert len(pdfium.PdfDocument(app.config["PDF_DIR"] / "three-pages.pdf")) == 3  # stored file untouched


def test_calendar(app, client):
    bid = bill_id(app, BILL["reference"])
    html = client.get("/kalendar?mesec=2026-10").get_data(as_text=True)
    assert "Oktobar 2026" in html and "?mesec=2026-09" in html and "?mesec=2026-11" in html
    assert f"/racun/{bid}" in html and "Rok za plaćanje" in html  # due 15.10.2026
    assert "15.10." in html
    assert client.get("/kalendar?mesec=nesto").status_code == 200  # falls back to this month


def test_guide(client):
    html = client.get("/uputstvo").get_data(as_text=True)
    assert "Uputstvo" in html and 'id="ips"' in html
    assert "Odštampaj račun" in html and 'class="to-top"' in html
    assert ">Uputstvo</a>" in html  # page name in the header


def test_header_title_follows_page(client):
    assert ">RačunTracker</a>" in client.get("/").get_data(as_text=True)
    assert ">Kalendar</a>" in client.get("/kalendar").get_data(as_text=True)
    assert ">Podešavanja</a>" in client.get("/podesavanja/").get_data(as_text=True)
