"""Build Bakong KHQR payment strings (EMVCo merchant-presented QR, as specified by the NBC KHQR guide).

A KHQR string is a list of TLV fields: 2-digit tag + 2-digit length + value, ending with a CRC16 checksum.
The MD5 of the final string identifies the payment when asking Bakong whether it has been paid.
"""

import hashlib
import time
from decimal import Decimal

import segno

CURRENCY_CODES = {"USD": "840", "KHR": "116"}


def _tlv(tag: str, value: str) -> str:
    if len(value) > 99:
        raise ValueError(f"KHQR field {tag} is too long ({len(value)} characters)")
    return f"{tag}{len(value):02d}{value}"


def crc16_ccitt(data: str) -> str:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF), as 4 uppercase hex digits."""
    crc = 0xFFFF
    for byte in data.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def format_amount(amount: Decimal | float | str, currency: str) -> str:
    value = Decimal(str(amount))
    if currency == "KHR":
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def build_khqr(
    *,
    account_id: str,
    account_information: str | None = None,
    acquiring_bank: str | None = None,
    merchant_name: str,
    merchant_city: str,
    amount: Decimal | float | str,
    currency: str = "USD",
    bill_number: str | None = None,
    store_label: str | None = None,
    expires_in_seconds: int = 15 * 60,
    now_ms: int | None = None,
) -> str:
    """Return a dynamic (one-time, fixed amount) individual KHQR string.

    Some banks (e.g. ABA) use one shared Bakong ID such as "abaakhppxxx@abaa" for all customers and
    identify the customer's account by `account_information` (the account number) and `acquiring_bank`.
    """
    if currency not in CURRENCY_CODES:
        raise ValueError("Currency must be USD or KHR")
    if "@" not in account_id or len(account_id) > 32:
        raise ValueError("Bakong account ID looks invalid (expected e.g. name@bank, max 32 characters)")
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms

    account = _tlv("00", account_id)
    if account_information:
        account += _tlv("01", account_information[:32])
    if acquiring_bank:
        account += _tlv("02", acquiring_bank[:32])

    additional = ""
    if bill_number:
        additional += _tlv("01", bill_number[:25])
    if store_label:
        additional += _tlv("03", store_label[:25])

    timestamps = _tlv("00", str(now_ms)) + _tlv("01", str(now_ms + expires_in_seconds * 1000))

    payload = (
        _tlv("00", "01")  # payload format indicator
        + _tlv("01", "12")  # point of initiation: 12 = dynamic (amount included)
        + _tlv("29", account)  # individual Bakong account
        + _tlv("52", "5999")  # merchant category code
        + _tlv("53", CURRENCY_CODES[currency])
        + _tlv("54", format_amount(amount, currency))
        + _tlv("58", "KH")
        + _tlv("59", merchant_name[:25])
        + _tlv("60", merchant_city[:15])
        + (_tlv("62", additional) if additional else "")
        + _tlv("99", timestamps)
        + "6304"
    )
    return payload + crc16_ccitt(payload)


def build_from_template(
    template: str,
    *,
    amount: Decimal | float | str,
    currency: str = "USD",
    bill_number: str | None = None,
    expires_in_seconds: int = 15 * 60,
    now_ms: int | None = None,
) -> str:
    """Turn your own bank's static KHQR (e.g. ABA "Receive money" QR) into a one-time QR for an amount.

    The receiving-account fields (29/30), name, city and any bank-specific fields are copied exactly as your
    bank wrote them, so the bank app accepts them. Only the amount, currency, bill number and timestamps change.
    """
    if currency not in CURRENCY_CODES:
        raise ValueError("Currency must be USD or KHR")
    template = template.strip()
    if not is_valid_khqr(template):
        raise ValueError("BAKONG_KHQR_TEMPLATE is not a valid KHQR string (bad checksum)")
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    fields = parse_tlv(template[:-8])  # drop "6304" + CRC
    fields["01"] = "12"  # dynamic: amount included
    fields["53"] = CURRENCY_CODES[currency]
    fields["54"] = format_amount(amount, currency)
    if bill_number:
        additional = parse_tlv(fields.get("62", ""))
        additional["01"] = bill_number[:25]
        fields["62"] = "".join(_tlv(t, v) for t, v in sorted(additional.items()))
    fields["99"] = _tlv("00", str(now_ms)) + _tlv("01", str(now_ms + expires_in_seconds * 1000))
    payload = "".join(_tlv(t, v) for t, v in sorted(fields.items())) + "6304"
    return payload + crc16_ccitt(payload)


def template_account_id(template: str) -> str | None:
    """The Bakong account ID inside a KHQR (sub-field 00 of field 29 or 30)."""
    fields = parse_tlv(template.strip()[:-8]) if template else {}
    for tag in ("29", "30"):
        if tag in fields:
            return parse_tlv(fields[tag]).get("00")
    return None


def parse_tlv(data: str) -> dict[str, str]:
    """Split a TLV string into {tag: value} (one level only)."""
    fields, i = {}, 0
    while i < len(data):
        tag, length = data[i : i + 2], int(data[i + 2 : i + 4])
        fields[tag] = data[i + 4 : i + 4 + length]
        i += 4 + length
    return fields


def is_valid_khqr(data: str) -> bool:
    return len(data) > 8 and data[-8:-4] == "6304" and crc16_ccitt(data[:-4]) == data[-4:]


def md5(data: str) -> str:
    return hashlib.md5(data.encode("utf-8")).hexdigest()


def qr_svg_data_uri(data: str) -> str:
    """Render the KHQR string as an SVG QR code, ready for <img src="...">."""
    return segno.make(data, error="m").svg_data_uri(scale=8, border=0, dark="#000000")
