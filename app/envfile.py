"""Reads and updates .env from the settings page. Changes apply after a restart."""
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import dotenv_values

# (key, label, tip, secret): secret values are never sent to the browser; an empty field keeps the saved value
FIELDS = (
    ("APP_PASSWORD", "Lozinka za prijavu", "Lozinka kojom se prijavljuješ u aplikaciju.", True),
    ("SECRET_KEY", "Ključ za šifrovanje",
     "Dugačak nasumičan niz kojim su potpisane prijave i šifrovan Gmail app password. Promena odjavljuje sve i app password mora ponovo da se upiše.", True),
    ("GMAIL_ADDRESS", "Gmail adresa (rezervna)", "Koristi se samo ako Gmail adresa nije upisana u delu Gmail.", False),
    ("GMAIL_APP_PASSWORD", "Gmail app password (rezervni)", "Koristi se samo ako Gmail podaci nisu upisani u delu Gmail.", True),
    ("GMAIL_LABEL", "Podrazumevana labela", "Gmail labela kad u delu Gmail nije upisana nijedna. Prazno: Racuni.", False),
    ("MAX_AMOUNT", "Granica iznosa (RSD)", "Račun veći od ovog iznosa dobija oznaku proveriti. Prazno: 100000.", False),
)
REQUIRED = {"SECRET_KEY", "APP_PASSWORD"}
SECRETS = {key for key, *_, secret in FIELDS if secret}


def read(path: Path) -> dict[str, str]:
    return {k: v or "" for k, v in dotenv_values(path).items()} if path.exists() else {}


def validate(values: dict[str, str]) -> str | None:
    """Error message for the merged values, or None."""
    if any("\n" in v or "\r" in v for v in values.values()):
        return "Vrednosti ne smeju da imaju novi red."
    if any("${" in v for v in values.values()):  # python-dotenv expands it even inside quotes
        return "Vrednosti ne smeju da imaju ${."
    if missing := [k for k in REQUIRED if not values.get(k)]:
        return f"{', '.join(sorted(missing))} ne sme da bude prazan."
    if values.get("MAX_AMOUNT"):
        try:
            if Decimal(values["MAX_AMOUNT"]) <= 0:
                raise InvalidOperation
        except InvalidOperation:
            return "MAX_AMOUNT je pozitivan broj, npr. 100000."
    return None


def quote(value: str) -> str:
    if re.fullmatch(r"[\w@.,:/+-]*", value):
        return value
    if "'" not in value:  # single quotes: no escapes
        return f"'{value}'"
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write(path: Path, values: dict[str, str]) -> None:
    """Replaces KEY= lines in place, keeping comments and other keys; appends missing keys."""
    lines = path.read_text().splitlines() if path.exists() else []
    seen = set()
    for i, line in enumerate(lines):
        m = re.match(r"\s*(?:export\s+)?(\w+)\s*=", line)
        if m and m[1] in values:  # every occurrence: dotenv uses the last one
            lines[i] = f"{m[1]}={quote(values[m[1]])}"
            seen.add(m[1])
    lines += [f"{k}={quote(v)}" for k, v in values.items() if k not in seen]
    # Written in place, not replaced: Docker mounts .env as a single file
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
