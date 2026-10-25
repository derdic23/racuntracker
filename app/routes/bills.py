import imaplib
import io
from datetime import date
from decimal import Decimal
from itertools import groupby

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file,
                   send_from_directory, url_for)
from imap_tools.errors import ImapToolsError, MailboxLoginError

from .. import ips
from ..db import connect, mark_reported_debts, unknown_customer_ids
from ..fetcher import credentials, fetch

bp = Blueprint("bills", __name__)

MONTHS = ("januar", "februar", "mart", "april", "maj", "jun",
          "jul", "avgust", "septembar", "oktobar", "novembar", "decembar")


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DB_PATH"])
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def format_rsd(value) -> str:
    """"1604.36" -> "1.604,36" """
    if value in (None, ""):
        return "-"
    return f"{Decimal(value):,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def format_date(value) -> str:
    """"2026-10-15" -> "15.10.2026." """
    return date.fromisoformat(value).strftime("%d.%m.%Y.") if value else "-"


def format_account(value) -> str:
    """"205000000050610226" -> "205-506102-26" """
    if not value or len(value) != 18 or not value.isdigit():
        return value or "-"
    return f"{value[:3]}-{value[3:16].lstrip('0')}-{value[16:]}"


def billing_month(row) -> str:
    """"2026-09" from the period start, or from the issue date if the period is missing."""
    return (row["period_from"] or row["issue_date"] or row["created_at"])[:7]


def month_label(month: str) -> str:
    """"2026-09" -> "Septembar 2026" """
    year, m = month.split("-")
    return f"{MONTHS[int(m) - 1].capitalize()} {year}"


def days_left(row) -> int | None:
    return (date.fromisoformat(row["due_date"]) - date.today()).days if row["due_date"] else None


def imap_error(e: Exception) -> str:
    if isinstance(e, MailboxLoginError):
        return "Prijava na Gmail nije uspela: proveri adresu i app password."
    return f"Greška u vezi sa Gmail-om: {e}"


def get_bill(bill_id: int):
    bill = get_db().execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    if bill is None:
        abort(404)
    return bill


def profile_name(row) -> str:
    return row["profile"] or "Bez profila"


def group(rows) -> list[tuple[str, list[tuple[str, list]]]]:
    """[(month, [(profile, bills)])], keeping the order of rows within a profile."""
    return [(month_label(m), [(p, list(bs)) for p, bs in groupby(sorted(ms, key=profile_name), key=profile_name)])
            for m, ms in groupby(rows, key=billing_month)]


@bp.get("/")
def index():
    db = get_db()
    rows = db.execute("""
        SELECT b.*, p.full_name AS profile FROM bills b
        LEFT JOIN customer_ids c ON c.provider = b.provider AND c.customer_id = b.customer_id
        LEFT JOIN profiles p ON p.id = c.profile_id
    """).fetchall()
    # Unpaid: oldest month first, by due date. Paid: newest month first.
    unpaid = sorted((r for r in rows if r["status"] == "unpaid"), key=lambda r: (billing_month(r), r["due_date"] or "9999"))
    paid = sorted((r for r in rows if r["status"] == "paid"), key=lambda r: (billing_month(r), r["due_date"] or ""), reverse=True)
    profiles = db.execute("SELECT id, full_name FROM profiles ORDER BY full_name").fetchall()
    return render_template("list.html", unpaid=group(unpaid), paid=group(paid), days_left=days_left,
                           show_profiles=len({r["profile"] for r in rows}) > 1,
                           unknown=unknown_customer_ids(db), profiles=profiles)


@bp.post("/proveri-mejl")
def check_mail():
    db = get_db()
    address, password, label = credentials(db, current_app.config["SECRET_KEY"])
    if not (address and password):
        flash("Gmail nije podešen. Upiši adresu i app password u Podešavanjima.", "error")
        return redirect(url_for("bills.index"))
    try:
        # shortcut: runs inside the request (can take a while); the scheduler in phase 4 does this in the background
        results = fetch(db, address, password, label, current_app.config["PDF_DIR"], current_app.config["MAX_AMOUNT"])
    except (ImapToolsError, imaplib.IMAP4.error, OSError) as e:
        flash(imap_error(e), "error")
        return redirect(url_for("bills.index"))
    new = [r for r in results if r.bill_id]
    flash(f"Novih računa: {len(new)}." if new else "Nema novih računa.")
    if review := sum(1 for r in new if r.verification != "verified"):
        flash(f"Za proveru: {review}. Otvori račune označene sa \"proveriti\".", "error")
    if debts := mark_reported_debts(db):
        flash(f"mts prijavljuje neplaćene račune: {len(debts)}.", "error")
    return redirect(url_for("bills.index"))


@bp.get("/racun/<int:bill_id>")
def detail(bill_id: int):
    bill = get_bill(bill_id)
    reporter = None
    if bill["reported_unpaid_by"]:
        reporter = get_db().execute("SELECT id, reference FROM bills WHERE id = ?", (bill["reported_unpaid_by"],)).fetchone()
    payment_url = bill["payment_url"] if (bill["payment_url"] or "").startswith("https://") else None
    return render_template("detail.html", bill=bill, reporter=reporter, payment_url=payment_url,
                           days_left=days_left(bill), month=month_label(billing_month(bill)))


@bp.get("/racun/<int:bill_id>/qr.png")
def qr(bill_id: int):
    bill = get_bill(bill_id)
    if not bill["ips_string"]:
        abort(404)
    return send_file(io.BytesIO(ips.qr_png(bill["ips_string"])), mimetype="image/png",
                     as_attachment="preuzmi" in request.args, download_name=f"ips-{bill['reference']}.png")


@bp.get("/racun/<int:bill_id>/pdf")
def pdf(bill_id: int):
    bill = get_bill(bill_id)
    if not bill["pdf_path"]:
        abort(404)
    # send_from_directory refuses paths outside PDF_DIR
    return send_from_directory(current_app.config["PDF_DIR"], bill["pdf_path"], mimetype="application/pdf")


@bp.post("/racun/<int:bill_id>/placeno")
def toggle_paid(bill_id: int):
    bill = get_bill(bill_id)
    db = get_db()
    with db:
        if bill["status"] == "unpaid":
            db.execute("UPDATE bills SET status = 'paid', paid_at = ? WHERE id = ?", (date.today().isoformat(), bill_id))
        else:
            db.execute("UPDATE bills SET status = 'unpaid', paid_at = NULL WHERE id = ?", (bill_id,))
    return redirect(url_for("bills.detail", bill_id=bill_id))
