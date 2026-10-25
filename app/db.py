import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    address TEXT,
    city TEXT,
    phone TEXT
);

CREATE TABLE IF NOT EXISTS customer_ids (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    profile_id INTEGER REFERENCES profiles(id) ON DELETE SET NULL,
    UNIQUE (provider, customer_id)
);

CREATE TABLE IF NOT EXISTS bills (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    customer_id TEXT,
    sub_account TEXT,
    bill_number TEXT,
    reference TEXT UNIQUE,
    model TEXT,
    recipient_account TEXT,
    amount TEXT,                -- Decimal as text, e.g. "1604.36"
    previous_debt TEXT,
    issue_date TEXT,            -- ISO dates
    due_date TEXT,
    period_from TEXT,
    period_to TEXT,
    ips_string TEXT,
    payment_url TEXT,
    pdf_path TEXT,              -- file name in DATA_DIR/pdfs
    status TEXT NOT NULL DEFAULT 'unpaid' CHECK (status IN ('unpaid', 'paid')),
    verification TEXT NOT NULL CHECK (verification IN ('verified', 'needs_review', 'suspicious')),
    review_notes TEXT,
    paid_at TEXT,
    -- Later bill whose "dug iz prethodnog perioda" shows this one was not paid
    reported_unpaid_by INTEGER REFERENCES bills(id) ON DELETE SET NULL,
    gmail_message_id TEXT UNIQUE,  -- RFC Message-ID header
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

BILL_COLUMNS = (
    "provider", "customer_id", "sub_account", "bill_number", "reference", "model",
    "recipient_account", "amount", "previous_debt", "issue_date", "due_date",
    "period_from", "period_to", "ips_string", "payment_url",
)


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(bills)")}
    if "reported_unpaid_by" not in columns:  # databases created before this column existed
        conn.execute("ALTER TABLE bills ADD COLUMN reported_unpaid_by INTEGER REFERENCES bills(id) ON DELETE SET NULL")
    return conn


def mark_reported_debts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Flag bills that a later bill reports as unpaid (debt from the previous period).

    The previous bill is the one of the same customer and sub-account whose period ends the day
    before the later bill's period starts. Runs over all bills, so the order of import does not matter.
    Returns the newly flagged bills with the reporting bill's reference and issue date.
    """
    pairs = conn.execute("""
        SELECT p.id, p.reference, p.period_from, p.period_to, p.status, p.paid_at,
               b.id AS reporter_id, b.reference AS reporter_reference, b.issue_date AS reporter_issue_date
        FROM bills b
        JOIN bills p ON p.provider = b.provider AND p.customer_id = b.customer_id
            AND p.sub_account = b.sub_account AND p.period_to = date(b.period_from, '-1 day')
        WHERE CAST(b.previous_debt AS REAL) > 0 AND p.reported_unpaid_by IS NULL
    """).fetchall()
    with conn:
        for p in pairs:
            conn.execute("UPDATE bills SET reported_unpaid_by = ? WHERE id = ?", (p["reporter_id"], p["id"]))
            # Marked paid before the later bill was issued, yet mts still counts it as debt
            if p["status"] == "paid" and (p["paid_at"] or "") < p["reporter_issue_date"]:
                note = f"mts u računu {p['reporter_reference']} prijavljuje da ovaj račun nije plaćen."
                conn.execute(
                    "UPDATE bills SET status = 'unpaid', paid_at = NULL, "
                    "review_notes = COALESCE(review_notes || char(10), '') || ? WHERE id = ?",
                    (note, p["id"]),
                )
    return pairs


def get_settings(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}


def set_settings(conn: sqlite3.Connection, **values: str) -> None:
    with conn:
        conn.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            values.items(),
        )


def unknown_customer_ids(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Customer IDs from bills that are not in customer_ids yet (to ask which profile they belong to)."""
    return conn.execute("""
        SELECT DISTINCT provider, customer_id FROM bills b
        WHERE customer_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM customer_ids c WHERE c.provider = b.provider AND c.customer_id = b.customer_id)
        ORDER BY provider, customer_id
    """).fetchall()


def has_message(conn: sqlite3.Connection, message_id: str) -> bool:
    return conn.execute("SELECT 1 FROM bills WHERE gmail_message_id = ?", (message_id,)).fetchone() is not None


def has_reference(conn: sqlite3.Connection, reference: str) -> bool:
    return conn.execute("SELECT 1 FROM bills WHERE reference = ?", (reference,)).fetchone() is not None


def insert_bill(conn, bill, *, verification: str, notes: list[str], pdf_path: str | None, message_id: str) -> int | None:
    """Returns the new id, or None if the message or the reference is already stored."""
    values = {c: getattr(bill, c) for c in BILL_COLUMNS}
    values = {k: (None if v is None else str(v)) for k, v in values.items()}
    values.update(
        pdf_path=pdf_path,
        verification=verification,
        review_notes="\n".join(notes) or None,
        gmail_message_id=message_id,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    cur = conn.execute(
        f"INSERT INTO bills ({', '.join(values)}) VALUES ({', '.join('?' * len(values))}) ON CONFLICT DO NOTHING",
        tuple(values.values()),
    )
    return cur.lastrowid if cur.rowcount else None
