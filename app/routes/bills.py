import calendar
import imaplib
import io
import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import groupby

import pypdfium2 as pdfium
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for
from imap_tools.errors import ImapToolsError
from werkzeug.security import safe_join

from .. import ips
from ..db import connect, get_settings, unknown_customer_ids
from ..fetcher import imap_error
from ..scheduler import check_mail as run_check

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


def format_datetime(value) -> str:
    """"2026-10-15T08:30:00" -> "15.10.2026. 08:30" """
    return datetime.fromisoformat(value).strftime("%d.%m.%Y. %H:%M")


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
    # Newest month first, latest due date first
    newest = lambda r: (billing_month(r), r["due_date"] or "")
    unpaid = sorted((r for r in rows if r["status"] == "unpaid"), key=newest, reverse=True)
    paid = sorted((r for r in rows if r["status"] == "paid"), key=newest, reverse=True)
    profiles = db.execute("SELECT id, full_name FROM profiles ORDER BY full_name").fetchall()
    return render_template("list.html", unpaid=group(unpaid), paid=group(paid), days_left=days_left,
                           unpaid_count=len(unpaid), paid_count=len(paid),
                           show_profiles=len({r["profile"] for r in rows}) > 1,
                           unknown=unknown_customer_ids(db), profiles=profiles, settings=get_settings(db))


@bp.get("/uputstvo")
def guide():
    return render_template("guide.html")


@bp.get("/kalendar")
def calendar_view():
    try:
        first = date.fromisoformat(request.args.get("mesec", "") + "-01")
    except ValueError:
        first = date.today().replace(day=1)
    month = first.isoformat()[:7]
    rows = get_db().execute(
        "SELECT * FROM bills WHERE substr(issue_date, 1, 7) = ? OR substr(due_date, 1, 7) = ?", (month, month)
    ).fetchall()
    # day -> [(kind, bill)]: the bill arrived (issue date) or is due that day
    events: dict[date, list] = {}
    for r in rows:
        for kind, column in (("stigao", "issue_date"), ("rok", "due_date")):
            if (r[column] or "")[:7] == month:
                events.setdefault(date.fromisoformat(r[column]), []).append((kind, r))
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(first.year, first.month)
    previous = (first - timedelta(days=1)).isoformat()[:7]
    following = (first + timedelta(days=31)).isoformat()[:7]
    return render_template("calendar.html", weeks=weeks, events=events, first=first, title=month_label(month),
                           previous=previous, following=following, today=date.today(),
                           agenda=sorted(((d, k, b) for d, es in events.items() for k, b in es), key=lambda e: e[0]))


@bp.post("/proveri-mejl")
def check_mail():
    try:
        checked = run_check(get_db(), current_app.config["SECRET_KEY"], current_app.config["PDF_DIR"],
                            current_app.config["MAX_AMOUNT"])
    except (ImapToolsError, imaplib.IMAP4.error, OSError) as e:
        flash(imap_error(e), "error")
        return redirect(url_for("bills.index"))
    if checked is None:
        flash("Gmail nije podešen. Upiši adresu i app password u Podešavanjima.", "error")
        return redirect(url_for("bills.index"))
    results, debts = checked
    new = [r for r in results if r.bill_id]
    flash(f"Novih računa: {len(new)}." if new else "Nema novih računa.")
    if review := sum(1 for r in new if r.verification != "verified"):
        flash(f"Za proveru: {review}. Otvori račune označene sa \"proveriti\".", "error")
    if debts:
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
    # safe_join refuses paths outside PDF_DIR
    path = safe_join(str(current_app.config["PDF_DIR"]), bill["pdf_path"])
    if path is None or not os.path.isfile(path):
        abort(404)
    if "ceo" in request.args:
        return send_file(path, mimetype="application/pdf", download_name=bill["pdf_path"])
    # For printing: the bill is always on page 1; the rest is a service list and ads
    src, out = pdfium.PdfDocument(path), pdfium.PdfDocument.new()
    out.import_pages(src, [0])
    buf = io.BytesIO()
    out.save(buf)
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf", download_name=bill["pdf_path"])


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
