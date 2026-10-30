import base64
import json
from datetime import date
from decimal import Decimal

import pytest

import invoapi
from invoapi import Response


class FakeTransport(invoapi.Transport):
    """Replays queued responses and records what was sent."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    def send(self, method, url, headers, body, timeout):
        self.sent.append({"method": method, "url": url, "headers": headers, "body": body})
        return self.responses.pop(0) if self.responses else Response(500, {}, b"{}")

    def last_json(self):
        return json.loads(self.sent[-1]["body"])


def reply(status, body, headers=None):
    return Response(status, headers or {}, json.dumps(body).encode())


@pytest.fixture
def slept():
    return []


@pytest.fixture
def make(slept):
    def factory(*responses, retries=2):
        transport = FakeTransport(responses)
        client = invoapi.Client("inv_test_key", transport=transport, max_retries=retries, sleep=slept.append)
        return client, transport

    return factory


def test_generate_sends_the_invoice_and_returns_the_document(make):
    client, transport = make(
        reply(
            200,
            {
                "success": True,
                "format": "xrechnung",
                "valid": True,
                "validation": {"status": "valid", "valid": True, "issues": []},
                "totals": {
                    "net": "1000.00",
                    "tax": "190.00",
                    "gross": "1190.00",
                    "payable": "1190.00",
                    "currency": "EUR",
                },
                "document": {
                    "mime_type": "application/xml",
                    "filename": "RE-1.xml",
                    "content": "<Invoice/>",
                    "encoding": "utf-8",
                },
            },
        )
    )
    document = client.generate({"invoice_number": "RE-1"}, format="xrechnung", syntax="ubl")

    sent = transport.sent[0]
    assert sent["method"] == "POST"
    assert sent["url"] == "https://api.invoapi.de/api/v1/generate"
    assert sent["headers"]["Authorization"] == "Bearer inv_test_key"
    assert sent["headers"]["User-Agent"].startswith("invoapi-python/")
    assert transport.last_json() == {
        "format": "xrechnung",
        "syntax": "ubl",
        "output": "xml",
        "validate": True,
        "invoice": {"invoice_number": "RE-1"},
    }
    assert document.is_valid is True
    assert document.content == b"<Invoice/>"
    assert document.text == "<Invoice/>"
    assert document.filename == "RE-1.xml"
    assert document.totals["gross"] == "1190.00"
    assert document.validation.status == "valid"


def test_decimals_and_dates_are_sent_as_strings(make):
    client, transport = make(reply(200, {"totals": {}}))
    client.calculate({"issue_date": date(2026, 10, 30), "items": [{"unit_price": Decimal("19.90")}]})
    assert transport.last_json()["invoice"] == {"issue_date": "2026-10-30", "items": [{"unit_price": "19.90"}]}


def test_pdf_content_is_decoded_and_saved(make, tmp_path, monkeypatch):
    client, _ = make(
        reply(
            200,
            {
                "valid": True,
                "document": {
                    "mime_type": "application/pdf",
                    "filename": "RE-1.pdf",
                    "content_base64": base64.b64encode(b"%PDF-1.7 bytes").decode(),
                    "encoding": "base64",
                },
            },
        )
    )
    document = client.generate({}, format="zugferd", output="pdf")
    assert document.content == b"%PDF-1.7 bytes"
    assert document.mime_type == "application/pdf"
    monkeypatch.chdir(tmp_path)
    assert document.save() == "RE-1.pdf"
    assert (tmp_path / "RE-1.pdf").read_bytes() == b"%PDF-1.7 bytes"
    assert document.save(tmp_path / "other.pdf").endswith("other.pdf")


def test_validate_accepts_bytes_text_and_paths(make, tmp_path):
    report_body = {
        "status": "invalid",
        "valid": False,
        "result": {
            "status": "invalid",
            "valid": False,
            "issues": [
                {"severity": "error", "rule": "BR-DE-15", "message": "Leitweg-ID fehlt"},
                {"severity": "warning", "rule": "BR-X", "message": "Hinweis"},
            ],
        },
    }
    path = tmp_path / "eingang.xml"
    path.write_bytes(b"<Invoice/>")
    client, transport = make(reply(200, report_body), reply(200, report_body), reply(200, report_body))
    expected = {"content_base64": base64.b64encode(b"<Invoice/>").decode()}

    for source in (b"<Invoice/>", "<Invoice/>", path):
        report = client.validate(source)
        assert transport.last_json() == expected
    assert report.is_valid is False
    assert report.status == "invalid"
    assert [issue["rule"] for issue in report.errors] == ["BR-DE-15"]
    assert len(report.warnings) == 1
    assert len(report.issues) == 2


def test_convert_to_json_returns_the_dict_and_to_xml_a_document(make):
    client, transport = make(
        reply(200, {"success": True, "invoice": {"invoice_number": "RE-1"}}),
        reply(200, {"document": {"mime_type": "application/xml", "filename": "x.xml", "content": "<x/>"}}),
    )
    assert client.convert("<x/>", "json")["invoice"]["invoice_number"] == "RE-1"
    assert isinstance(client.convert({"invoice_number": "RE-1"}, "xml", format="cii"), invoapi.Document)
    assert transport.last_json() == {"target": "xml", "format": "cii", "invoice": {"invoice_number": "RE-1"}}


def test_render_returns_the_raw_bytes(make):
    client, _ = make(Response(200, {"content-type": "application/pdf"}, b"%PDF-1.7"))
    assert client.render("<x/>") == b"%PDF-1.7"


def test_formats_unwraps_the_list(make):
    client, transport = make(reply(200, {"formats": [{"id": "xrechnung"}, {"id": "zugferd"}]}))
    assert [entry["id"] for entry in client.formats()] == ["xrechnung", "zugferd"]
    assert transport.sent[0]["method"] == "GET"
    assert transport.sent[0]["body"] is None


def test_rate_limit_is_retried_after_the_requested_wait(make, slept):
    client, transport = make(
        reply(429, {"error": {"code": "RATE_LIMITED", "message": "Zu viele Aufrufe."}}, {"retry-after": "7"}),
        reply(200, {"totals": {"gross": "1.00"}}),
    )
    assert client.calculate({"invoice_number": "RE-1"})["totals"]["gross"] == "1.00"
    assert slept == [7]
    assert len(transport.sent) == 2


def test_rate_limit_gives_up_after_max_retries(make):
    limited = reply(429, {"error": {"code": "RATE_LIMITED", "message": "Zu viele Aufrufe."}}, {"retry-after": "3"})
    client, transport = make(limited, limited, retries=1)
    with pytest.raises(invoapi.RateLimitError) as caught:
        client.calculate({})
    assert caught.value.retry_after == 3
    assert caught.value.code == "RATE_LIMITED"
    assert len(transport.sent) == 2


def test_quota_exhausted_is_not_retried(make, slept):
    client, transport = make(
        reply(
            402,
            {
                "error": {
                    "code": "QUOTA_EXHAUSTED",
                    "message": "Ihr kostenloses Kontingent ist aufgebraucht",
                    "request_id": "req_1",
                }
            },
        )
    )
    with pytest.raises(invoapi.QuotaExhaustedError) as caught:
        client.generate({})
    assert "aufgebraucht" in str(caught.value)
    assert caught.value.request_id == "req_1"
    assert caught.value.http_status == 402
    assert len(transport.sent) == 1
    assert slept == []


def test_authentication_and_input_errors_map_to_their_own_types(make):
    client, _ = make(
        reply(401, {"error": {"code": "UNAUTHORIZED", "message": "Ungültiger Schlüssel"}}),
        reply(
            422,
            {
                "error": {
                    "code": "INVALID_INVOICE",
                    "message": "Pflichtfeld fehlt",
                    "details": [{"field": "seller.name"}],
                }
            },
        ),
        retries=0,
    )
    with pytest.raises(invoapi.AuthenticationError):
        client.generate({})
    with pytest.raises(invoapi.InvalidRequestError) as caught:
        client.generate({})
    assert caught.value.details[0]["field"] == "seller.name"
    assert isinstance(caught.value, invoapi.InvoapiError)


def test_server_errors_are_retried_then_raised(make, slept):
    down = reply(503, {"error": {"code": "VALIDATOR_UNAVAILABLE", "message": "Prüfdienst nicht erreichbar"}})
    client, transport = make(down, down, down)
    with pytest.raises(invoapi.ServiceUnavailableError):
        client.validate("<x/>")
    assert len(transport.sent) == 3
    assert slept == [1, 2]


def test_non_json_error_bodies_still_raise_a_clear_error(make):
    client, _ = make(Response(502, {"x-request-id": "req_9"}, b"<html>Bad Gateway</html>"), retries=0)
    with pytest.raises(invoapi.ServiceUnavailableError) as caught:
        client.health()
    assert "HTTP 502" in str(caught.value)
    assert caught.value.request_id == "req_9"


def test_the_key_comes_from_the_environment_and_is_required(monkeypatch):
    monkeypatch.setenv("INVOAPI_API_KEY", "inv_env_key")
    assert invoapi.Client()._api_key == "inv_env_key"
    assert "inv_env_key" not in repr(invoapi.Client())
    monkeypatch.delenv("INVOAPI_API_KEY")
    with pytest.raises(ValueError):
        invoapi.Client()
    with pytest.raises(ValueError):
        invoapi.Client("  ")


def test_base_url_is_configurable(make):
    transport = FakeTransport([reply(200, {"status": "ok"})])
    client = invoapi.Client("k", base_url="https://staging.example/", transport=transport)
    assert client.health() == {"status": "ok"}
    assert transport.sent[0]["url"] == "https://staging.example/api/v1/health"
