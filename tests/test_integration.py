"""Against a real invoapi instance. Skipped unless INVOAPI_API_KEY is set.

    INVOAPI_API_KEY=inv_… pytest -m integration

Every call here spends allowance on the account the key belongs to.
"""

import os
import re

import pytest

import invoapi

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("INVOAPI_API_KEY"), reason="INVOAPI_API_KEY not set"),
]

BASE_URL = os.environ.get("INVOAPI_BASE_URL", invoapi.DEFAULT_BASE_URL)

INVOICE = {
    "invoice_number": "RE-2026-0001",
    "issue_date": "2026-10-28",
    "due_date": "2026-11-27",
    "currency": "EUR",
    "buyer_reference": "04011000-12345-34",
    "seller": {
        "name": "Muster GmbH",
        "street": "Musterstraße 1",
        "postal_code": "10115",
        "city": "Berlin",
        "country_code": "DE",
        "vat_id": "DE123456789",
        "email": "rechnung@muster.de",
        "phone": "+49 30 1234567",
    },
    "buyer": {
        "name": "Beispiel GmbH",
        "street": "Teststraße 10",
        "postal_code": "20095",
        "city": "Hamburg",
        "country_code": "DE",
        "vat_id": "DE987654321",
        "email": "kreditoren@beispiel.de",
    },
    "items": [
        {"name": "Beratung", "quantity": 8, "unit": "HUR", "unit_price": 145, "vat_rate": 19},
        {"name": "Handbuch", "quantity": 25, "unit": "C62", "unit_price": 19.9, "vat_rate": 7},
    ],
    "payment": {
        "means_code": "58",
        "iban": "DE02120300000000202051",
        "bic": "BYLADEM1001",
        "terms": "Zahlbar innerhalb von 30 Tagen ohne Abzug.",
    },
    "delivery": {"date": "2026-10-27"},
}


@pytest.fixture(scope="module")
def client():
    return invoapi.Client(base_url=BASE_URL)


def test_formats_and_health(client):
    assert "xrechnung" in [entry["id"] for entry in client.formats()]
    assert client.health()["status"] == "ok"


@pytest.mark.parametrize(
    "format,syntax",
    [
        ("xrechnung", "ubl"),
        ("xrechnung", "cii"),
        ("zugferd", None),
        ("en16931", "ubl"),
        ("peppol", None),
    ],
)
def test_generate_every_format_valid(client, format, syntax):
    document = client.generate(INVOICE, format=format, syntax=syntax)
    assert document.is_valid, f"{format}/{syntax} not valid"
    assert "RE-2026-0001" in document.text


def test_zugferd_pdf_round_trip(client):
    pdf = client.generate(INVOICE, format="zugferd", output="pdf", profile="en16931")
    assert pdf.is_valid
    assert pdf.content.startswith(b"%PDF")

    assert client.validate(pdf.content).is_valid
    assert client.parse(pdf.content)["invoice"]["invoice_number"] == "RE-2026-0001"
    assert client.detect(pdf.content)["format"] == "zugferd"


def test_validate_finds_the_broken_rule(client):
    xml = client.generate(INVOICE, format="xrechnung", syntax="ubl").text
    broken = re.sub(r"<cbc:BuyerReference>[^<]*</cbc:BuyerReference>", "", xml, count=1)
    report = client.validate(broken)
    assert not report.is_valid
    assert report.errors


def test_convert_and_calculate(client):
    xml = client.generate(INVOICE, format="xrechnung", syntax="ubl").content
    cii = client.convert(xml, "xml", format="xrechnung", syntax="cii")
    assert cii.is_valid in (True, None)
    assert "CrossIndustryInvoice" in cii.text
    assert client.calculate(INVOICE)["totals"]["payable"] == "1912.73"


def test_helpful_errors(client):
    with pytest.raises(invoapi.InvalidRequestError) as caught:
        client.generate({"invoice_number": "unvollständig"})
    assert caught.value.http_status == 422
    with pytest.raises(invoapi.AuthenticationError):
        invoapi.Client("inv_live_falsch", base_url=BASE_URL).calculate(INVOICE)
