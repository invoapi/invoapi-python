from __future__ import annotations

import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .errors import APIConnectionError


@dataclass
class Response:
    status: int
    #: Header names in lower case.
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


class Transport:
    """Sends one HTTP request. Replace it in tests or to route through a proxy."""

    def send(self, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float) -> Response:
        raise NotImplementedError


class UrllibTransport(Transport):
    """The standard library's HTTP client, so the package needs no dependencies."""

    def send(self, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float) -> Response:
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as reply:
                return Response(reply.status, _lower(reply.headers), reply.read())
        except urllib.error.HTTPError as error:
            # 4xx and 5xx arrive as exceptions; their body carries the API's message.
            return Response(error.code, _lower(error.headers), error.read())
        except (urllib.error.URLError, socket.timeout, ssl.SSLError, ConnectionError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise APIConnectionError(f"invoapi ist nicht erreichbar: {reason}") from error


def _lower(headers) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {name.lower(): value for name, value in headers.items()} if headers else {}
