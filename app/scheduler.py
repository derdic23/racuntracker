"""Checks Gmail in the background every N minutes (Podešavanja > Interval provere)."""
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from .db import connect, get_settings, mark_reported_debts, set_settings
from .fetcher import Result, credentials, fetch, imap_error

DEFAULT_INTERVAL = 60  # minutes
LOCK = threading.Lock()  # one check at a time: the scheduler or "Proveri mejl sada"


def interval(settings: dict[str, str]) -> int:
    """Minutes between checks; 0 turns the background check off."""
    value = settings.get("check_interval")
    return int(value) if value is not None else DEFAULT_INTERVAL


def check_mail(conn: sqlite3.Connection, secret_key: str, pdf_dir: Path, max_amount: Decimal) -> tuple[list[Result], list] | None:
    """Fetches new bills and flags unpaid ones. None if Gmail is not set up.

    Saves the time and the error of the last check, then re-raises the error.
    """
    address, password, label = credentials(conn, secret_key)
    if not (address and password):
        return None
    with LOCK:
        error = ""
        try:
            results = fetch(conn, address, password, label, pdf_dir, max_amount)
            return results, mark_reported_debts(conn)
        except Exception as e:
            error = imap_error(e)
            raise
        finally:
            set_settings(conn, last_check_at=datetime.now().isoformat(timespec="seconds"), last_check_error=error)


def due(settings: dict[str, str], now: datetime) -> bool:
    minutes = interval(settings)
    last = settings.get("last_check_at")
    return bool(minutes) and (not last or now - datetime.fromisoformat(last) >= timedelta(minutes=minutes))


def tick(app) -> None:
    conn = connect(app.config["DB_PATH"])
    try:
        if due(get_settings(conn), datetime.now()):
            check_mail(conn, app.config["SECRET_KEY"], app.config["PDF_DIR"], app.config["MAX_AMOUNT"])
    except Exception:  # keep the thread alive; the error is saved and shown on the list
        app.logger.exception("Automatska provera mejla nije uspela")
    finally:
        conn.close()


def start(app) -> None:
    """Starts the background thread. Run only one process (gunicorn --workers 1), or every process checks Gmail."""
    def loop():
        while True:
            tick(app)
            time.sleep(60)  # the interval is re-read every minute, so a change applies without a restart
    threading.Thread(target=loop, name="mail-check", daemon=True).start()
