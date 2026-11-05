from imap_tools import MailMessage

from .base import ParsedBill, Provider
from .mts import MtsProvider

# The only place a new provider needs to be registered
PROVIDERS: list[Provider] = [MtsProvider()]


def find_provider(message: MailMessage) -> Provider | None:
    return next((p for p in PROVIDERS if p.matches(message)), None)


def all_subjects() -> list[str]:
    return [p.search_subject for p in PROVIDERS]
