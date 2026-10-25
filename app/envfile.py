"""Reads and updates .env from the settings page. Changes apply after a restart."""
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import dotenv_values

# (key, secret): secret values are never shown; an empty field keeps the saved value
FIELDS = (
    ("SECRET_KEY", True),
    ("APP_PASSWORD", True),
    ("GMAIL_ADDRESS", False),
    ("GMAIL_APP_PASSWORD", True),
    ("GMAIL_LABEL", False),
    ("MAX_AMOUNT", False),
)
REQUIRED = {"SECRET_KEY", "APP_PASSWORD"}


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
