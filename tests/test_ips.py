import io
from decimal import Decimal

import pytest
import zxingcpp
from PIL import Image

from app import ips

SAMPLE = ("K:PR|V:01|C:1|R:205000000050610226|N:Telekom Srbija A.D.\r\nBeograd|I:RSD1604,36"
          "|P:PETAR PETROVIĆ|SF:189|S:MTS Račun 09/2026 12345678/3|RO:97953000210000001")


def test_parse_and_generate_round_trip():
    fields = ips.parse(SAMPLE)
    assert fields["R"] == "205000000050610226"
    assert fields["N"] == "Telekom Srbija A.D.\r\nBeograd"
    assert ips.amount(fields) == Decimal("1604.36")
    assert ips.generate(fields) == SAMPLE


def test_generate_orders_fields_and_skips_empty():
    s = ips.generate({"RO": "97123", "K": "PR", "V": "01", "C": "1", "R": "1" * 18, "N": "X",
                      "I": "RSD1,00", "SF": "189", "P": ""})
    assert s == "K:PR|V:01|C:1|R:111111111111111111|N:X|I:RSD1,00|SF:189|RO:97123"


@pytest.mark.parametrize("bad", ["", "K:PR|V:01", "K:PR|V:01|C:1|R:1|N:X|I:RSD1,00|SF:189|broken"])
def test_parse_rejects_invalid(bad):
    with pytest.raises(ValueError):
        ips.parse(bad)


def test_amount_formatting():
    assert ips.format_amount(Decimal("1604.36")) == "RSD1604,36"
    assert ips.format_amount(Decimal("5")) == "RSD5,00"
    with pytest.raises(ValueError):
        ips.amount({"I": "EUR1,00"})


def test_qr_png_is_readable():
    image = Image.open(io.BytesIO(ips.qr_png(SAMPLE)))
    assert [r.text for r in zxingcpp.read_barcodes(image)] == [SAMPLE]
