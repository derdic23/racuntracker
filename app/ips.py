"""NBS IPS QR string: `key:value` pairs separated by `|`."""
import io
from decimal import Decimal

import qrcode

# Order defined by the NBS IPS standard
FIELD_ORDER = ("K", "V", "C", "R", "N", "I", "P", "SF", "S", "PM", "PI", "RO")
REQUIRED = {"K", "V", "C", "R", "N", "I", "SF"}


def parse(text: str) -> dict[str, str]:
    fields = {}
    for part in text.strip().split("|"):
        key, sep, value = part.partition(":")
        if not sep or not key:
            raise ValueError(f"Invalid IPS field: {part!r}")
        fields[key] = value
    missing = REQUIRED - fields.keys()
    if missing:
        raise ValueError(f"Missing IPS fields: {', '.join(sorted(missing))}")
    return fields


def generate(fields: dict[str, str]) -> str:
    missing = REQUIRED - {k for k, v in fields.items() if v}
    if missing:
        raise ValueError(f"Missing IPS fields: {', '.join(sorted(missing))}")
    return "|".join(f"{k}:{fields[k]}" for k in FIELD_ORDER if fields.get(k))


def amount(fields: dict[str, str]) -> Decimal:
    """`I:RSD1604,36` -> Decimal('1604.36')"""
    value = fields["I"]
    if not value.startswith("RSD"):
        raise ValueError(f"Unsupported currency: {value!r}")
    return Decimal(value[3:].replace(",", "."))


def format_amount(value: Decimal) -> str:
    return "RSD" + f"{value:.2f}".replace(".", ",")


def qr_png(text: str) -> bytes:
    buf = io.BytesIO()
    qrcode.make(text, error_correction=qrcode.constants.ERROR_CORRECT_M).save(buf, format="PNG")
    return buf.getvalue()
