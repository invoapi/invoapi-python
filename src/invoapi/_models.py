from __future__ import annotations

import base64
import os
from typing import Any


class ValidationReport:
    """The verdict of the official rule sets (KoSIT, EN 16931 Schematron, Peppol BIS).

    ``is_valid`` is only ever true when a rule set actually ran: a document the
    service cannot check reports status ``unsupported_validation``, never "valid".
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self.raw = data

    @property
    def is_valid(self) -> bool:
        return self.raw.get("valid") is True

    @property
    def status(self) -> str:
        """``valid``, ``invalid`` or ``unsupported_validation``."""
        return str(self.raw.get("status") or "unsupported_validation")

    @property
    def detected_format(self) -> str | None:
        return self.raw.get("detected_format")

    @property
    def issues(self) -> list[dict[str, Any]]:
        """Every finding: severity, rule id, message, explanation, field, expected and actual value."""
        return list(self.raw.get("issues") or [])

    @property
    def errors(self) -> list[dict[str, Any]]:
        """Findings that make the document invalid."""
        return self._with_severity("error")

    @property
    def warnings(self) -> list[dict[str, Any]]:
        return self._with_severity("warning")

    def _with_severity(self, severity: str) -> list[dict[str, Any]]:
        return [issue for issue in self.issues if str(issue.get("severity", "")).lower() == severity]

    def __repr__(self) -> str:
        return f"<ValidationReport status={self.status!r} errors={len(self.errors)}>"


class Document:
    """A produced invoice file — XML or a hybrid ZUGFeRD PDF — plus what was checked."""

    def __init__(self, data: dict[str, Any]) -> None:
        #: The full API response (``GenerateResponse`` or ``ConvertResponse``).
        self.raw = data

    @property
    def _document(self) -> dict[str, Any]:
        return self.raw.get("document") or {}

    @property
    def content(self) -> bytes:
        """The file's bytes, ready to store or send."""
        document = self._document
        if document.get("content_base64") is not None:
            return base64.b64decode(document["content_base64"])
        return str(document.get("content") or "").encode("utf-8")

    @property
    def text(self) -> str:
        """The XML as text. Not meaningful for a PDF."""
        return self.content.decode("utf-8")

    @property
    def filename(self) -> str:
        return str(self._document.get("filename") or "rechnung")

    @property
    def mime_type(self) -> str:
        return str(self._document.get("mime_type") or "application/octet-stream")

    @property
    def is_valid(self) -> bool | None:
        """True when the official validator confirmed the document; None when it was not run."""
        valid = self.raw.get("valid")
        return None if valid is None else bool(valid)

    @property
    def validation(self) -> ValidationReport | None:
        data = self.raw.get("validation")
        return ValidationReport(data) if data is not None else None

    @property
    def totals(self) -> dict[str, str]:
        """Net, tax, gross and payable amount as decimal strings, plus the currency."""
        return dict(self.raw.get("totals") or {})

    @property
    def warnings(self) -> list[str]:
        return list(self.raw.get("warnings") or [])

    def save(self, path: str | os.PathLike[str] | None = None) -> str:
        """Write the file, by default under its own filename. Returns the path written."""
        target = os.fspath(path) if path is not None else self.filename
        with open(target, "wb") as handle:
            handle.write(self.content)
        return target

    def __repr__(self) -> str:
        return f"<Document {self.filename!r} {self.mime_type} valid={self.is_valid}>"
