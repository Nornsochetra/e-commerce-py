import pytest

from app import khqr


def test_crc16_matches_standard_check_value():
    # CRC-16/CCITT-FALSE check value for "123456789" is 0x29B1.
    assert khqr.crc16_ccitt("123456789") == "29B1"


def test_build_khqr_fields():
    data = khqr.build_khqr(
        account_id="setec@aclb", merchant_name="Setec Shop", merchant_city="Phnom Penh",
        amount="12.50", bill_number="ORD-00001", store_label="Setec Shop",
        expires_in_seconds=900, now_ms=1_763_200_000_000,
    )
    assert khqr.is_valid_khqr(data)
    fields = khqr.parse_tlv(data)
    assert fields["00"] == "01"
    assert fields["01"] == "12"  # dynamic QR
    assert khqr.parse_tlv(fields["29"]) == {"00": "setec@aclb"}
    assert fields["52"] == "5999"
    assert fields["53"] == "840"
    assert fields["54"] == "12.5"
    assert fields["58"] == "KH"
    assert fields["59"] == "Setec Shop"
    assert fields["60"] == "Phnom Penh"
    assert khqr.parse_tlv(fields["62"]) == {"01": "ORD-00001", "03": "Setec Shop"}
    assert khqr.parse_tlv(fields["99"]) == {"00": "1763200000000", "01": "1763200900000"}
    assert data.startswith("000201010212")


def test_amount_formatting():
    assert khqr.format_amount("10.00", "USD") == "10"
    assert khqr.format_amount("0.5", "USD") == "0.5"
    assert khqr.format_amount("7.25", "USD") == "7.25"
    assert khqr.format_amount("15000", "KHR") == "15000"


def test_tampered_string_fails_crc():
    data = khqr.build_khqr(account_id="a@b", merchant_name="M", merchant_city="PP", amount=1)
    assert not khqr.is_valid_khqr(data.replace("5401", "5402"))


def test_rejects_bad_account():
    with pytest.raises(ValueError):
        khqr.build_khqr(account_id="no-at-sign", merchant_name="M", merchant_city="PP", amount=1)


def test_qr_image_is_svg():
    assert khqr.qr_svg_data_uri("hello").startswith("data:image/svg+xml")


def test_shared_bank_id_with_account_number():
    # ABA style: shared Bakong ID + the customer's account number and bank name.
    data = khqr.build_khqr(
        account_id="abaakhppxxx@abaa", account_information="000123456", acquiring_bank="ABA Bank",
        merchant_name="Setec Shop", merchant_city="Phnom Penh", amount="1", now_ms=1_763_200_000_000,
    )
    assert khqr.is_valid_khqr(data)
    assert khqr.parse_tlv(khqr.parse_tlv(data)["29"]) == {
        "00": "abaakhppxxx@abaa", "01": "000123456", "02": "ABA Bank",
    }


def test_build_from_bank_template_keeps_account_fields():
    from app.khqr import _tlv, build_from_template, crc16_ccitt, is_valid_khqr, parse_tlv, template_account_id

    account = _tlv("00", "abaakhppxxx@abaa") + _tlv("01", "123456789012345") + _tlv("02", "ABA Bank")
    body = (_tlv("00", "01") + _tlv("01", "11") + _tlv("30", account) + _tlv("52", "4829") + _tlv("53", "840")
            + _tlv("58", "KH") + _tlv("59", "SOK DARA") + _tlv("60", "PHNOM PENH")
            + _tlv("62", _tlv("02", "012345678")) + "6304")
    template = body + crc16_ccitt(body)

    qr = build_from_template(template, amount="0.01", bill_number="ORD-00007", now_ms=1_700_000_000_000)
    fields = parse_tlv(qr[:-8])
    assert is_valid_khqr(qr)
    assert fields["01"] == "12" and fields["54"] == "0.01" and fields["53"] == "840"
    assert fields["30"] == account and fields["52"] == "4829" and fields["59"] == "SOK DARA"
    assert parse_tlv(fields["62"]) == {"01": "ORD-00007", "02": "012345678"}
    assert template_account_id(template) == "abaakhppxxx@abaa"
