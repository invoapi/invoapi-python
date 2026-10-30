"""Python client for the invoapi.de e-invoicing API.

Create XRechnung, ZUGFeRD / Factur-X, EN 16931, UBL, CII and Peppol invoices,
validate them against the official rule sets (KoSIT), convert and parse them.
"""

from ._client import DEFAULT_BASE_URL, Client
from ._models import Document, ValidationReport
from ._transport import Response, Transport, UrllibTransport
from ._version import __version__
from .errors import (
    APIConnectionError,
    AuthenticationError,
    InvalidRequestError,
    InvoapiError,
    QuotaExhaustedError,
    RateLimitError,
    ServiceUnavailableError,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "APIConnectionError",
    "AuthenticationError",
    "Client",
    "Document",
    "InvalidRequestError",
    "InvoapiError",
    "QuotaExhaustedError",
    "RateLimitError",
    "Response",
    "ServiceUnavailableError",
    "Transport",
    "UrllibTransport",
    "ValidationReport",
    "__version__",
]
