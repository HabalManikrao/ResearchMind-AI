"""SSRF protection for outbound HTTP (spec §21).

`validate_url` rejects non-HTTP(S) schemes and hosts that resolve to private,
loopback, link-local, or otherwise reserved addresses. `safe_get` validates before
fetching. Used by agents that hit external hosts so that a URL derived from user or
model input can never make the server fetch internal infrastructure.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from app.config import get_settings


class UnsafeURLError(ValueError):
    pass


def _is_blocked_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def validate_url(url: str) -> None:
    """Raise UnsafeURLError if the URL is not a safe public HTTP(S) target."""
    if get_settings().allow_private_fetch:
        return
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"Blocked non-HTTP scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no host")
    if host.lower() in ("localhost", "localhost.localdomain"):
        raise UnsafeURLError("Blocked localhost")

    # Resolve every A/AAAA record; reject if any is private/reserved.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Cannot resolve host {host!r}: {exc}") from exc
    for info in infos:
        ip = info[4][0]
        if _is_blocked_ip(ip):
            raise UnsafeURLError(f"Blocked private/reserved address for {host!r}: {ip}")


async def safe_get(
    url: str, *, client: httpx.AsyncClient, **kwargs
) -> httpx.Response:
    """Validate then GET. Raises UnsafeURLError before any request is made."""
    validate_url(url)
    return await client.get(url, **kwargs)
