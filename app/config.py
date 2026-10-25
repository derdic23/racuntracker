import os
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)

DATA_DIR = Path(os.environ.get("DATA_DIR") or BASE_DIR / "data")
DB_PATH = DATA_DIR / "racuntracker.db"
PDF_DIR = DATA_DIR / "pdfs"

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
GMAIL_LABEL = os.environ.get("GMAIL_LABEL") or "Racuni"

MAX_AMOUNT = Decimal(os.environ.get("MAX_AMOUNT") or "100000")

# Web app: session signing key and the single login password
SECRET_KEY = os.environ.get("SECRET_KEY", "")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
