import imaplib
import sqlite3

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from imap_tools.errors import ImapToolsError

from ..crypto import decrypt, encrypt
from ..db import get_settings, set_settings
from ..fetcher import credentials, imap_error, try_login
from ..providers import PROVIDERS
from ..scheduler import interval
from .bills import get_db

bp = Blueprint("settings", __name__, url_prefix="/podesavanja")

PROFILE_FIELDS = ("full_name", "address", "city", "phone")


@bp.get("/")
def index():
    db = get_db()
    s = get_settings(db)
    gmail = {
        "address": s.get("gmail_address", ""),
        "label": s.get("gmail_label") or current_app.config["GMAIL_LABEL"],
        "has_password": bool(s.get("gmail_password")),
        "interval": interval(s),
        "last_check_at": s.get("last_check_at"),
        "last_check_error": s.get("last_check_error"),
        # Saved with a different SECRET_KEY
        "password_broken": bool(s.get("gmail_password")) and decrypt(current_app.config["SECRET_KEY"], s["gmail_password"]) is None,
    }
    return render_template(
        "settings.html",
        profiles=db.execute("SELECT * FROM profiles ORDER BY full_name").fetchall(),
        customer_ids=db.execute("SELECT * FROM customer_ids ORDER BY provider, customer_id").fetchall(),
        providers=[p.name for p in PROVIDERS],
        gmail=gmail,
    )


@bp.post("/profil")
def save_profile():
    values = {f: request.form.get(f, "").strip() or None for f in PROFILE_FIELDS}
    if not values["full_name"]:
        flash("Ime i prezime je obavezno.", "error")
        return redirect(url_for("settings.index"))
    db = get_db()
    with db:
        if profile_id := request.form.get("id", type=int):
            db.execute(f"UPDATE profiles SET {', '.join(f'{f} = ?' for f in values)} WHERE id = ?",
                       (*values.values(), profile_id))
        else:
            db.execute(f"INSERT INTO profiles ({', '.join(values)}) VALUES (?, ?, ?, ?)", tuple(values.values()))
    flash("Profil je sačuvan.")
    return redirect(url_for("settings.index"))


@bp.post("/profil/<int:profile_id>/obrisi")
def delete_profile(profile_id: int):
    db = get_db()
    with db:  # its customer IDs stay, without a profile
        db.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
    flash("Profil je obrisan.")
    return redirect(url_for("settings.index"))


@bp.post("/sifra")
def save_customer_id():
    """Adds a customer ID or moves it to another profile. Also used by the "new customer ID" notice on the list."""
    provider = request.form.get("provider", "")
    customer_id = request.form.get("customer_id", "").strip()
    profile_id = request.form.get("profile_id", type=int)  # empty: no profile
    back = url_for("bills.index") if request.form.get("back") == "list" else url_for("settings.index")
    if provider not in {p.name for p in PROVIDERS} or not customer_id:
        flash("Izaberi provajdera i upiši šifru korisnika.", "error")
        return redirect(back)
    db = get_db()
    try:
        with db:
            db.execute("INSERT INTO customer_ids (provider, customer_id, profile_id) VALUES (?, ?, ?) "
                       "ON CONFLICT (provider, customer_id) DO UPDATE SET profile_id = excluded.profile_id",
                       (provider, customer_id, profile_id))
    except sqlite3.IntegrityError:  # profile deleted in the meantime
        flash("Izabrani profil ne postoji.", "error")
        return redirect(back)
    flash(f"Šifra korisnika {customer_id} je sačuvana.")
    return redirect(back)


@bp.post("/sifra/<int:row_id>/obrisi")
def delete_customer_id(row_id: int):
    db = get_db()
    with db:
        db.execute("DELETE FROM customer_ids WHERE id = ?", (row_id,))
    flash("Šifra korisnika je obrisana.")
    return redirect(url_for("settings.index"))


@bp.post("/gmail")
def save_gmail():
    minutes = request.form.get("interval", type=int)
    if minutes is None or not 0 <= minutes <= 1440:
        flash("Interval provere je broj minuta od 0 do 1440.", "error")
        return redirect(url_for("settings.index"))
    values = {
        "check_interval": str(minutes),
        "gmail_address": request.form.get("address", "").strip(),
        "gmail_label": request.form.get("label", "").strip() or current_app.config["GMAIL_LABEL"],
    }
    if password := request.form.get("password", "").replace(" ", ""):  # Google shows app passwords in groups of 4
        values["gmail_password"] = encrypt(current_app.config["SECRET_KEY"], password)
    set_settings(get_db(), **values)
    flash("Gmail podešavanja su sačuvana.")
    return redirect(url_for("settings.index"))


@bp.post("/gmail/test")
def test_gmail():
    address, password, label = credentials(get_db(), current_app.config["SECRET_KEY"])
    if not (address and password):
        flash("Upiši Gmail adresu i app password.", "error")
        return redirect(url_for("settings.index"))
    try:
        flash(try_login(address, password, label))
    except (ImapToolsError, imaplib.IMAP4.error, OSError) as e:
        flash(imap_error(e), "error")
    return redirect(url_for("settings.index"))
