from imap_tools.errors import MailboxLoginError

from app import fetcher
from app.crypto import decrypt, encrypt
from app.db import connect, get_settings
from app.fetcher import Result
from app.routes import bills
from test_web import app, client, csrf  # noqa: F401 (fixtures)


def settings(app) -> dict:
    conn = connect(app.config["DB_PATH"])
    try:
        return get_settings(conn)
    finally:
        conn.close()


def post(client, path, **data):
    return client.post(path, data={"csrf": csrf(client, "/podesavanja/"), **data}, follow_redirects=True)


def test_encrypt_round_trip():
    token = encrypt("kljuc", "abcd efgh")
    assert "abcd" not in token
    assert decrypt("kljuc", token) == "abcd efgh"
    assert decrypt("drugi kljuc", token) is None


def test_settings_requires_login(app):
    assert app.test_client().get("/podesavanja/").status_code == 302


def test_profiles_and_customer_ids(client):
    html = client.get("/").get_data(as_text=True)
    assert "Nova šifra korisnika: mts 12345678" in html

    assert "obavezno" in post(client, "/podesavanja/profil", full_name=" ").get_data(as_text=True)
    post(client, "/podesavanja/profil", full_name="Pera Perić", city="Beograd")
    post(client, "/podesavanja/profil", full_name="Mika Mikić")
    html = client.get("/podesavanja/").get_data(as_text=True)
    assert 'value="Pera Perić"' in html and 'value="Beograd"' in html

    # From the notice on the list: assign the new customer ID to a profile
    r = post(client, "/podesavanja/sifra", provider="mts", customer_id="12345678", profile_id="1", back="list")
    html = r.get_data(as_text=True)
    assert "Nova šifra korisnika" not in html
    assert "<h3>Pera Perić</h3>" not in html  # only one profile has bills

    post(client, "/podesavanja/sifra", provider="mts", customer_id="87654321", profile_id="2")
    post(client, "/podesavanja/sifra", provider="eps", customer_id="1")  # unknown provider: refused
    html = client.get("/podesavanja/").get_data(as_text=True)
    assert "87654321" in html and "</span> 1</span>" not in html

    post(client, "/podesavanja/profil", id="1", full_name="Pera Perić", city="Novi Sad")
    assert 'value="Novi Sad"' in client.get("/podesavanja/").get_data(as_text=True)

    # Deleting the profile keeps the customer ID, without a profile
    post(client, "/podesavanja/profil/1/obrisi")
    html = client.get("/podesavanja/").get_data(as_text=True)
    assert "Pera Perić" not in html and "</span> 12345678</span>" in html
    assert "Nova šifra korisnika" not in client.get("/").get_data(as_text=True)


def test_list_groups_by_profile(app, client):
    post(client, "/podesavanja/profil", full_name="Pera Perić")
    post(client, "/podesavanja/sifra", provider="mts", customer_id="12345678", profile_id="1")
    conn = connect(app.config["DB_PATH"])
    with conn:  # second customer ID without a profile
        conn.execute("UPDATE bills SET customer_id = '99999999' WHERE id = (SELECT MIN(id) FROM bills)")
    conn.close()
    html = client.get("/").get_data(as_text=True)
    assert "<h3>Pera Perić</h3>" in html and "<h3>Bez profila</h3>" in html


def test_gmail_password_is_encrypted(app, client):
    post(client, "/podesavanja/gmail", address="ja@gmail.com", password="abcd efgh ijkl mnop", label="")
    s = settings(app)
    assert s["gmail_address"] == "ja@gmail.com" and s["gmail_label"] == app.config["GMAIL_LABEL"]
    assert "abcd" not in s["gmail_password"]
    assert decrypt("test", s["gmail_password"]) == "abcdefghijklmnop"

    html = client.get("/podesavanja/").get_data(as_text=True)
    assert "abcd" not in html and "sačuvan, ostavi prazno" in html

    # Empty password field keeps the saved one
    post(client, "/podesavanja/gmail", address="ja@gmail.com", password="", label="Racuni")
    assert settings(app)["gmail_password"] == s["gmail_password"]

    # Saved with another SECRET_KEY
    conn = connect(app.config["DB_PATH"])
    with conn:
        conn.execute("UPDATE settings SET value = ? WHERE key = 'gmail_password'", (encrypt("drugi", "x"),))
    conn.close()
    assert "ne može da se pročita" in client.get("/podesavanja/").get_data(as_text=True)


class FakeMailBox:
    def __init__(self, host):
        pass

    def login(self, address, password):
        if password != "dobra":
            raise MailboxLoginError(("NO", [b"Invalid credentials"]), "OK")
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    class folder:
        @staticmethod
        def exists(name):
            return name == "Racuni"


def test_gmail_connection(client, monkeypatch):
    monkeypatch.setattr(fetcher, "MailBox", FakeMailBox)
    post(client, "/podesavanja/gmail", address="ja@gmail.com", password="dobra", label="Racuni")
    assert "Veza radi." in post(client, "/podesavanja/gmail/test").get_data(as_text=True)
    post(client, "/podesavanja/gmail", address="ja@gmail.com", password="", label="Nema")
    assert "labela &#39;Nema&#39; ne postoji" in post(client, "/podesavanja/gmail/test").get_data(as_text=True)
    post(client, "/podesavanja/gmail", address="ja@gmail.com", password="losa", label="Racuni")
    assert "Prijava na Gmail nije uspela" in post(client, "/podesavanja/gmail/test").get_data(as_text=True)


def test_check_mail_now(client, monkeypatch):
    monkeypatch.setattr(fetcher.config, "GMAIL_ADDRESS", "")
    assert "Gmail nije podešen" in post(client, "/proveri-mejl").get_data(as_text=True)

    calls = []
    def fake_fetch(conn, address, password, label, pdf_dir, max_amount):
        calls.append((address, password, label))
        return [Result(None, "needs_review", [], bill_id=7), Result(None, "verified", [], bill_id=None)]
    monkeypatch.setattr(bills, "fetch", fake_fetch)
    post(client, "/podesavanja/gmail", address="ja@gmail.com", password="tajna", label="Racuni")
    html = post(client, "/proveri-mejl").get_data(as_text=True)
    assert calls == [("ja@gmail.com", "tajna", "Racuni")]
    assert "Novih računa: 1." in html and "Za proveru: 1." in html

    def failing_fetch(*args):
        raise OSError("mreža nije dostupna")
    monkeypatch.setattr(bills, "fetch", failing_fetch)
    assert "mreža nije dostupna" in post(client, "/proveri-mejl").get_data(as_text=True)
