"""Manual commands.

    python cli.py fetch                 # check Gmail now (credentials from .env)
    python cli.py parse FILE.eml...     # parse local .eml files, print the result
    python cli.py parse --save FILE...  # ...and store them in the database
"""
import argparse
import sys
from pathlib import Path

from imap_tools import MailMessage

from app import config
from app.db import connect, mark_reported_debts
from app.fetcher import Result, check, fetch, process_message
from app.providers import find_provider


def print_result(r: Result) -> None:
    b = r.bill
    print(f"[{r.verification}] {b.provider} {b.customer_id}/{b.sub_account} poziv na broj {b.reference}")
    print(f"    iznos {b.amount} din, rok {b.due_date}, period {b.period_from} - {b.period_to}")
    if b.previous_debt:
        print(f"    UPOZORENJE: dug iz prethodnog perioda {b.previous_debt} din")
    for note in r.notes:
        print(f"    - {note}")


def report_debts(conn) -> None:
    for p in mark_reported_debts(conn):
        print(f"NIJE PLAĆEN: račun {p['reference']} ({p['period_from']} - {p['period_to']}), "
              f"prema dugu u računu {p['reporter_reference']}")


def cmd_parse(args) -> int:
    conn = connect(config.DB_PATH) if args.save else None
    for path in args.files:
        message = MailMessage.from_bytes(Path(path).read_bytes())
        if conn:
            result = process_message(conn, message, config.PDF_DIR, config.MAX_AMOUNT)
            if result is None:
                print(f"{path}: nije račun ili je već obrađen")
                continue
            if result.bill_id is None:
                print(f"{path}: račun sa ovim pozivom na broj već postoji u bazi")
        else:
            provider = find_provider(message)
            if provider is None:
                print(f"{path}: nije prepoznat kao račun")
                continue
            bill = provider.parse(message)
            result = Result(bill, *check(bill, config.MAX_AMOUNT), bill_id=None)
        print(f"{path}:")
        print_result(result)
    if conn:
        report_debts(conn)
    return 0


def cmd_fetch(args) -> int:
    if not (config.GMAIL_ADDRESS and config.GMAIL_APP_PASSWORD):
        print("Podesi GMAIL_ADDRESS i GMAIL_APP_PASSWORD u .env", file=sys.stderr)
        return 1
    conn = connect(config.DB_PATH)
    results = fetch(conn, config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD, config.GMAIL_LABEL, config.PDF_DIR, config.MAX_AMOUNT)
    for r in results:
        print_result(r)
    print(f"Novih računa: {sum(1 for r in results if r.bill_id)}")
    report_debts(conn)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="RačunTracker")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch", help="proveri Gmail").set_defaults(func=cmd_fetch)
    p = sub.add_parser("parse", help="pročitaj lokalne .eml fajlove")
    p.add_argument("--save", action="store_true", help="sačuvaj u bazu")
    p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_parse)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
