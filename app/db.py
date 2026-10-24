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
    return conn


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
