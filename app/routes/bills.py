import io
from datetime import date
from decimal import Decimal
from itertools import groupby

from flask import Blueprint, abort, current_app, g, redirect, render_template, request, send_file, send_from_directory, url_for

from .. import ips
from ..db import connect

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


def get_bill(bill_id: int):
    bill = get_db().execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    if bill is None:
        abort(404)
    return bill


@bp.get("/")
def index():
    rows = get_db().execute("SELECT * FROM bills").fetchall()
    # Unpaid: oldest month first, by due date. Paid: newest month first.
    unpaid = sorted((r for r in rows if r["status"] == "unpaid"), key=lambda r: (billing_month(r), r["due_date"] or "9999"))
    paid = sorted((r for r in rows if r["status"] == "paid"), key=lambda r: (billing_month(r), r["due_date"] or ""), reverse=True)
    group = lambda items: [(month_label(m), list(bs)) for m, bs in groupby(items, key=billing_month)]
    return render_template("list.html", unpaid=group(unpaid), paid=group(paid), days_left=days_left)


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
