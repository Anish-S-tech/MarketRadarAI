"""SSRF protection for user-supplied source URLs."""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from app.config import settings


class UnsafeURLError(ValueError):
    pass


def _is_private(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def validate_url_syntax(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError("Only http(s) URLs are allowed")
    if not parsed.hostname:
        raise UnsafeURLError("URL has no host")
    if parsed.username or parsed.password:
        raise UnsafeURLError("Credentials in URLs are not allowed")
    return url


async def assert_public_url(url: str) -> None:
    validate_url_syntax(url)
    if settings.allow_private_sources:
        return
    host = urlparse(url).hostname or ""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise UnsafeURLError(f"Cannot resolve host {host}") from e
    for info in infos:
        if _is_private(str(info[4][0])):
            raise UnsafeURLError(f"Host {host} resolves to a private address")
