
"""Unified IPv4-only HTTP/HTTPS network service.

All project HTTP requests must go through this module.

Responsibilities:
- Validate URL scheme, host, credentials, and port.
- Resolve and validate public IPv4 addresses.
- Pin each request to the validated DNS results.
- Verify the actual connected peer IP.
- Handle redirects manually and validate every redirect target.
- Enforce shared request deadlines, retries, and bounded response reads.
- Return the shared NetworkResult model.

This module does not parse subscriptions or validate TS/HLS streams.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

import aiohttp

import config
from models import NetworkResult


_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_RETRYABLE_ERRORS = (
    asyncio.TimeoutError,
    aiohttp.ClientConnectionError,
    aiohttp.ServerDisconnectedError,
)


@dataclass(frozen=True)
class _ValidatedURL:
    url: str
    hostname: str
    port: int
    is_https: bool


class _PinnedIPv4Resolver(aiohttp.abc.AbstractResolver):
    """Resolver that only returns IPv4 addresses validated beforehand."""

    def __init__(self, addresses: tuple[str, ...]) -> None:
        self._addresses = addresses

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: int = socket.AF_INET,
    ) -> list[dict]:
        if family not in (socket.AF_UNSPEC, socket.AF_INET):
            raise OSError("IPv6 resolution is forbidden.")

        return [
            {
                "hostname": host,
                "host": address,
                "port": port,
                "family": socket.AF_INET,
                "proto": socket.IPPROTO_TCP,
                "flags": 0,
            }
            for address in self._addresses
        ]

    async def close(self) -> None:
        return None


def _error_result(
    requested_url: str,
    message: str,
    *,
    content: bytes = b"",
    status_code: Optional[int] = None,
    final_url: Optional[str] = None,
    remote_ip: Optional[str] = None,
    content_type: Optional[str] = None,
    bytes_received: int = 0,
    redirects: tuple[str, ...] = (),
) -> NetworkResult:
    return NetworkResult(
        success=False,
        requested_url=requested_url,
        content=content,
        final_url=final_url,
        remote_ip=remote_ip,
        status_code=status_code,
        content_type=content_type,
        bytes_received=bytes_received,
        redirects=redirects,
        error=message,
    )


def _normalize_and_validate_url(url: str) -> _ValidatedURL:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("URL is empty or invalid.")

    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        raise ValueError("URL format is invalid.") from exc

    scheme = parts.scheme.lower()

    if scheme not in config.ALLOWED_URL_SCHEMES:
        raise ValueError("Only HTTP and HTTPS URLs are allowed.")

    if not parts.netloc or not parts.hostname:
        raise ValueError("URL host is missing.")

    if parts.username is not None or parts.password is not None:
        raise ValueError("URL userinfo is forbidden.")

    hostname = parts.hostname.rstrip(".").lower()

    if not hostname:
        raise ValueError("URL hostname is invalid.")

    # This project only supports IPv4. IPv6 literals are rejected.
    if ":" in hostname:
        raise ValueError("IPv6 addresses are forbidden.")

    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("URL port is invalid.") from exc

    if port is None:
        port = 443 if scheme == "https" else 80

    if not (
        config.MIN_TCP_PORT <= port <= config.MAX_TCP_PORT
    ):
        raise ValueError("URL port is outside the allowed range.")

    # Rebuild the URL without credentials or fragments.
    host_for_url = hostname

    netloc = (
        host_for_url
        if port == (443 if scheme == "https" else 80)
        else f"{host_for_url}:{port}"
    )

    normalized = urlunsplit(
        (
            scheme,
            netloc,
            parts.path or "/",
            parts.query,
            "",
        )
    )

    return _ValidatedURL(
        url=normalized,
        hostname=hostname,
        port=port,
        is_https=(scheme == "https"),
    )


async def _resolve_public_ipv4(
    hostname: str,
    port: int,
) -> tuple[str, ...]:
    """Resolve a hostname and reject the whole result if any IPv4 is unsafe."""

    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        if not isinstance(literal_ip, ipaddress.IPv4Address):
            raise ValueError("Only IPv4 addresses are allowed.")

        if not literal_ip.is_global:
            raise ValueError("Non-public IPv4 address is forbidden.")

        return (str(literal_ip),)

    loop = asyncio.get_running_loop()

    try:
        records = await asyncio.wait_for(
            loop.getaddrinfo(
                hostname,
                port,
                family=socket.AF_INET,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            ),
            timeout=config.DNS_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise asyncio.TimeoutError("DNS lookup timed out.") from exc
    except OSError as exc:
        raise OSError("DNS lookup failed.") from exc

    addresses: list[str] = []

    for record in records:
        address = record[4][0]

        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValueError("DNS returned an invalid address.") from exc

        if not isinstance(parsed, ipaddress.IPv4Address):
            raise ValueError("DNS returned a non-IPv4 address.")

        if not parsed.is_global:
            raise ValueError(
                "DNS result contains a non-public IPv4 address."
            )

        if address not in addresses:
            addresses.append(address)

    if not addresses:
        raise OSError("DNS returned no IPv4 addresses.")

    return tuple(addresses)


def _check_response_headers(
    response: aiohttp.ClientResponse,
) -> None:
    raw_headers = response.raw_headers

    if len(raw_headers) > config.MAX_HTTP_HEADERS_COUNT:
        raise ValueError("HTTP response has too many headers.")

    total_bytes = 0

    for name, value in raw_headers:
        line_size = len(name) + len(value) + 4

        if line_size > config.MAX_HTTP_HEADER_LINE_BYTES:
            raise ValueError("HTTP response header line is too large.")

        total_bytes += line_size

        if total_bytes > config.MAX_HTTP_HEADERS_BYTES:
            raise ValueError("HTTP response headers exceed size limit.")

    content_encoding = response.headers.get(
        "Content-Encoding", "identity"
    ).strip().lower()

    if content_encoding not in ("", "identity"):
        raise ValueError("Compressed HTTP responses are forbidden.")


def _get_actual_remote_ip(
    response: aiohttp.ClientResponse,
) -> str:
    connection = response.connection

    if connection is None:
        protocol = getattr(response, "_protocol", None)
        transport = getattr(protocol, "transport", None)
    else:
        transport = connection.transport

    if transport is None:
        raise OSError("Unable to inspect the actual remote connection.")

    peer = transport.get_extra_info("peername")

    if not peer or not peer[0]:
        raise OSError("Remote peer address is unavailable.")

    try:
        remote = ipaddress.ip_address(peer[0])
    except ValueError as exc:
        raise OSError("Remote peer address is invalid.") from exc

    if not isinstance(remote, ipaddress.IPv4Address):
        raise OSError("Connected peer is not IPv4.")

    if not remote.is_global:
        raise OSError("Connected peer is not a public IPv4 address.")

    return str(remote)


async def _read_limited(
    response: aiohttp.ClientResponse,
    max_bytes: int,
) -> tuple[bytes, bool]:
    """Read at most max_bytes plus one byte to detect overflow."""

    chunks: list[bytes] = []
    received = 0

    async for chunk in response.content.iter_chunked(16 * 1024):
        if not chunk:
            continue

        remaining = max_bytes - received

        if len(chunk) > remaining:
            if remaining > 0:
                chunks.append(chunk[:remaining])
                received += remaining

            return b"".join(chunks), True

        chunks.append(chunk)
        received += len(chunk)

        if received >= max_bytes:
            # Read one additional byte to distinguish exact size from overflow.
            extra = await response.content.read(1)

            if extra:
                return b"".join(chunks), True

            break

    return b"".join(chunks), False


async def _request_once(
    requested_url: str,
    max_bytes: int,
    deadline: float,
) -> NetworkResult:
    current_url = requested_url
    redirect_chain: list[str] = []
    last_remote_ip: Optional[str] = None

    for redirect_number in range(config.MAX_REDIRECTS + 1):
        remaining = deadline - asyncio.get_running_loop().time()

        if remaining <= 0:
            raise asyncio.TimeoutError("Request total budget exhausted.")

        validated = _normalize_and_validate_url(current_url)

        addresses = await _resolve_public_ipv4(
            validated.hostname,
            validated.port,
        )

        remaining = deadline - asyncio.get_running_loop().time()

        if remaining <= 0:
            raise asyncio.TimeoutError("Request total budget exhausted.")

        resolver = _PinnedIPv4Resolver(addresses)

        connector = aiohttp.TCPConnector(
            resolver=resolver,
            family=socket.AF_INET,
            use
