import os
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.environ.get("DATA_DIR") or BASE_DIR / "data")
DB_PATH = DATA_DIR / "racuntracker.db"
PDF_DIR = DATA_DIR / "pdfs"

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
GMAIL_LABEL = os.environ.get("GMAIL_LABEL") or "Racuni"

MAX_AMOUNT = Decimal(os.environ.get("MAX_AMOUNT") or "100000")
