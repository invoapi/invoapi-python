from __future__ import annotations

import base64
import json
import os
import platform
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable, Union

from ._models import Document, ValidationReport
from ._transport import Response, Transport, UrllibTransport
from ._version import __version__
from .errors import (
    AuthenticationError,
    InvalidRequestError,
    InvoapiError,
    QuotaExhaustedError,
    RateLimitError,
    ServiceUnavailableError,
)

#: A document as raw bytes, as XML text, or as the path of a file to read.
Source = Union[bytes, str, "os.PathLike[str]"]

DEFAULT_BASE_URL = "https://api.invoapi.de"


class Client:
    """Client for the invoapi.de e-invoicing API.

    >>> invoapi = Client()                      # reads INVOAPI_API_KEY
    >>> document = invoapi.generate(invoice, format="xrechnung")
    >>> document.save()                         # RE-2026-0001.xml

    Every method raises an :class:`~invoapi.errors.InvoapiError` subclass on refusal.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 90.0,
        max_retries: int = 2,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """
        :param api_key: falls back to the environment variable ``INVOAPI_API_KEY``
        :param max_retries: how often a 429 or 5xx is retried after the wait the API
            asks for (default 2, 0 disables)
        """
        key = (api_key if api_key is not None else os.environ.get("INVOAPI_API_KEY", "")).strip()
        if not key:
            raise ValueError(
                "Ein API-Schlüssel ist nötig. Sie finden ihn im Dashboard unter API-Schlüssel "
                "(oder setzen Sie INVOAPI_API_KEY)."
            )
        self._api_key = key
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.max_retries = max(0, int(max_retries))
        self._transport = transport or UrllibTransport()
        self._sleep = sleep

    def __repr__(self) -> str:
        # Never show the key.
        return f"<invoapi.Client {self.base_url}>"

    # ------------------------------------------------------------------ invoices

    def generate(
        self,
        invoice: Mapping[str, Any],
        *,
        format: str = "xrechnung",
        syntax: str | None = None,
        output: str = "xml",
        profile: str | None = None,
        validate: bool = True,
    ) -> Document:
        """Create an e-invoice from invoice data and check it against the official rule set.

        :param invoice: see https://invoapi.de/docs for the fields
        :param format: ``xrechnung`` | ``zugferd`` | ``en16931`` | ``ubl`` | ``cii`` | ``peppol``
        :param syntax: ``ubl`` or ``cii``; None takes the format's default
        :param output: ``xml``, or ``pdf`` for a hybrid ZUGFeRD PDF/A-3
        :param profile: ZUGFeRD profile, e.g. ``en16931``
        """
        body = _without_none(
            format=format, syntax=syntax, output=output, profile=profile, validate=validate, invoice=dict(invoice)
        )
        return Document(self._post("/api/v1/generate", body))

    def validate(self, document: Source) -> ValidationReport:
        """Check an existing e-invoice (XML or ZUGFeRD PDF) against its official rule set."""
        response = self._post("/api/v1/validate", {"content_base64": _encode(document)})
        return ValidationReport(response.get("result") or response)

    def detect(self, document: Source) -> dict[str, Any]:
        """Which standard, syntax and version a document is."""
        return self._post("/api/v1/detect", {"content_base64": _encode(document)})

    def parse(self, document: Source) -> dict[str, Any]:
        """Read an e-invoice back into structured data (seller, buyer, lines, totals)."""
        return self._post("/api/v1/parse", {"content_base64": _encode(document)})

    def convert(
        self,
        source: Source | Mapping[str, Any],
        target: str = "xml",
        *,
        format: str | None = None,
        syntax: str | None = None,
        profile: str | None = None,
    ) -> Any:
        """Convert a document (or invoice data) into another format, or into JSON.

        :param target: ``xml``, ``pdf``, ``html`` or ``json``
        :returns: a :class:`Document` for xml/pdf/html, the parsed invoice dict for json
        """
        body = _without_none(target=target, format=format, syntax=syntax, profile=profile)
        body.update(_source(source))
        response = self._post("/api/v1/convert", body)
        return response if target == "json" else Document(response)

    def render(self, source: Source | Mapping[str, Any], output: str = "pdf") -> bytes:
        """A readable rendering for people: HTML or PDF (without embedded XML)."""
        body: dict[str, Any] = {"output": output}
        body.update(_source(source))
        return self._request("POST", "/api/v1/render", body).body

    def calculate(self, invoice: Mapping[str, Any]) -> dict[str, Any]:
        """Totals, VAT breakdown and line amounts, exactly as the generator would compute them. Free of charge."""
        return self._post("/api/v1/calculate", {"invoice": dict(invoice)})

    # ------------------------------------------------------------------ service

    def formats(self) -> list[dict[str, Any]]:
        """Supported formats with syntaxes and versions."""
        data = _decode(self._request("GET", "/api/v1/formats"))
        formats = data.get("formats", data) if isinstance(data, dict) else data
        return list(formats.values()) if isinstance(formats, dict) else list(formats)

    def health(self) -> dict[str, Any]:
        data = _decode(self._request("GET", "/api/v1/health"))
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------ plumbing

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        data = _decode(self._request("POST", path, body))
        return data if isinstance(data, dict) else {}

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Response:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "User-Agent": f"invoapi-python/{__version__} Python/{platform.python_version()}",
        }
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body, ensure_ascii=False, default=_json_default).encode("utf-8")
        attempt = 0
        while True:
            response = self._transport.send(method, self.base_url + path, headers, payload, self.timeout)
            if response.status < 400:
                return response
            error = _error_for(response)
            retriable = isinstance(error, (RateLimitError, ServiceUnavailableError))
            if not retriable or attempt >= self.max_retries:
                raise error
            wait = error.retry_after if isinstance(error, RateLimitError) else 2**attempt
            self._sleep(max(1, min(wait, 120)))
            attempt += 1


def _without_none(**values: Any) -> dict[str, Any]:
    return {name: value for name, value in values.items() if value is not None}


def _read(document: Source) -> bytes:
    if isinstance(document, bytes):
        return document
    if isinstance(document, str):
        return document.encode("utf-8")
    return Path(document).read_bytes()


def _encode(document: Source) -> str:
    return base64.b64encode(_read(document)).decode("ascii")


def _source(source: Source | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return {"invoice": dict(source)}
    return {"content_base64": _encode(source)}


def _json_default(value: Any) -> Any:
    # Decimal amounts and dates are common in invoice data; send them as the API expects.
    from datetime import date
    from decimal import Decimal

    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} lässt sich nicht als JSON senden")


def _decode(response: Response) -> Any:
    try:
        return json.loads(response.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise InvoapiError("Unerwartete Antwort von invoapi (kein JSON).", response.status) from None


def _error_for(response: Response) -> InvoapiError:
    try:
        data = json.loads(response.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        data = None
    error: dict[str, Any] = {}
    if isinstance(data, dict) and isinstance(data.get("error"), dict):
        error = data["error"]
    status = response.status
    message = str(error.get("message") or f"invoapi antwortete mit HTTP {status}.")
    code = str(error["code"]) if error.get("code") is not None else None
    request_id = error.get("request_id") or response.header("x-request-id")
    details = error.get("details") if isinstance(error.get("details"), list) else []

    def make(kind: type[InvoapiError]) -> InvoapiError:
        return kind(message, http_status=status, code=code, request_id=request_id, details=details)

    if status == 429:
        try:
            retry_after = int(response.header("retry-after") or 60)
        except ValueError:
            retry_after = 60
        return RateLimitError(
            message, http_status=status, code=code, request_id=request_id, details=details, retry_after=retry_after
        )
    if status == 402 or code == "QUOTA_EXHAUSTED":
        return make(QuotaExhaustedError)
    if status in (401, 403):
        return make(AuthenticationError)
    if status >= 500:
        return make(ServiceUnavailableError)
    return make(InvalidRequestError)
