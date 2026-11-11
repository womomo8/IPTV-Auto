
"""Shared IPv4-only HTTP/HTTPS network service."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

import aiohttp

import config
from models import NetworkResult


_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class _ResponseReadError(Exception):
    """Preserve response bytes already consumed before a read failure."""

    def __init__(
        self,
        cause: Exception,
        content: bytes,
    ) -> None:
        super().__init__(type(cause).__name__)
        self.content = content
        self.bytes_received = len(content)
        self.cause_name = type(cause).__name__


class _PinnedIPv4Resolver(aiohttp.abc.AbstractResolver):
    """Return only IPv4 addresses already checked by this module."""

    def __init__(self, addresses: tuple[str, ...]) -> None:
        self.addresses = addresses

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: int = socket.AF_INET,
    ) -> list[dict]:
        if family not in (socket.AF_UNSPEC, socket.AF_INET):
            raise OSError("IPv6 is forbidden.")

        return [
            {
                "hostname": host,
                "host": address,
                "port": port,
                "family": socket.AF_INET,
                "proto": socket.IPPROTO_TCP,
                "flags": 0,
            }
            for address in self.addresses
        ]

    async def close(self) -> None:
        return None


def _failure(
    url: str,
    message: str,
    *,
    content: bytes = b"",
    bytes_received: Optional[int] = None,
    status_code: Optional[int] = None,
    final_url: Optional[str] = None,
    remote_ip: Optional[str] = None,
    content_type: Optional[str] = None,
    redirects: tuple[str, ...] = (),
) -> NetworkResult:
    if bytes_received is None:
        bytes_received = len(content)

    return NetworkResult(
        success=False,
        requested_url=url,
        content=content,
        final_url=final_url,
        remote_ip=remote_ip,
        status_code=status_code,
        content_type=content_type,
        bytes_received=bytes_received,
        redirects=redirects,
        error=message,
    )


def _validate_url(url: str) -> tuple[str, str, int]:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("URL is empty or invalid.")

    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        raise ValueError("URL format is invalid.") from exc

    scheme = parts.scheme.lower()

    if scheme not in config.ALLOWED_URL_SCHEMES:
        raise ValueError("Only HTTP and HTTPS are allowed.")

    if not parts.netloc or not parts.hostname:
        raise ValueError("URL host is missing.")

    if parts.username is not None or parts.password is not None:
        raise ValueError("URL userinfo is forbidden.")

    hostname = parts.hostname.rstrip(".").lower()

    if not hostname or ":" in hostname:
        raise ValueError("Invalid hostname or IPv6 address.")

    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("Invalid URL port.") from exc

    if port is None:
        port = 443 if scheme == "https" else 80

    if not config.MIN_TCP_PORT <= port <= config.MAX_TCP_PORT:
        raise ValueError("URL port is outside the allowed range.")

    default_port = 443 if scheme == "https" else 80
    netloc = hostname if port == default_port else f"{hostname}:{port}"

    normalized = urlunsplit(
        (scheme, netloc, parts.path or "/", parts.query, "")
    )

    return normalized, hostname, port


async def _resolve_public_ipv4(
    hostname: str,
    port: int,
) -> tuple[str, ...]:
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None

    if literal is not None:
        if not isinstance(literal, ipaddress.IPv4Address):
            raise ValueError("Only IPv4 addresses are allowed.")
        if not literal.is_global:
            raise ValueError("Non-public IPv4 address is forbidden.")
        return (str(literal),)

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
    except asyncio.TimeoutError:
        raise
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
            raise ValueError("DNS returned a non-public IPv4 address.")

        if address not in addresses:
            addresses.append(address)

    if not addresses:
        raise OSError("DNS returned no IPv4 addresses.")

    return tuple(addresses)


def _check_headers(response: aiohttp.ClientResponse) -> None:
    headers = response.raw_headers

    if len(headers) > config.MAX_HTTP_HEADERS_COUNT:
        raise ValueError("Too many HTTP headers.")

    total = 0

    for name, value in headers:
        line_size = len(name) + len(value) + 4

        if line_size > config.MAX_HTTP_HEADER_LINE_BYTES:
            raise ValueError("HTTP header line exceeds size limit.")

        total += line_size

        if total > config.MAX_HTTP_HEADERS_BYTES:
            raise ValueError("HTTP headers exceed total size limit.")

    encoding = response.headers.get(
        "Content-Encoding", "identity"
    ).strip().lower()

    if encoding not in ("", "identity"):
        raise ValueError("Compressed responses are forbidden.")


def _actual_remote_ip(response: aiohttp.ClientResponse) -> str:
    connection = response.connection

    if connection is not None:
        transport = connection.transport
    else:
        protocol = getattr(response, "_protocol", None)
        transport = getattr(protocol, "transport", None)

    if transport is None:
        raise OSError("Cannot inspect actual remote connection.")

    peer = transport.get_extra_info("peername")

    if not peer or not peer[0]:
        raise OSError("Remote peer address is unavailable.")

    try:
        address = ipaddress.ip_address(peer[0])
    except ValueError as exc:
        raise OSError("Invalid remote peer address.") from exc

    if not isinstance(address, ipaddress.IPv4Address):
        raise OSError("Connected peer is not IPv4.")

    if not address.is_global:
        raise OSError("Connected peer is not a public IPv4 address.")

    return str(address)


async def _read_limited(
    response: aiohttp.ClientResponse,
    max_bytes: int,
) -> tuple[bytes, bool, int]:
    """Read at most max_bytes and preserve bytes on interrupted reads.

    A known Content-Length equal to the bytes consumed is complete.
    With unknown Content-Length, at_eof() determines whether the body
    has ended when the read limit is reached. No extra byte is read.
    """
    chunks: list[bytes] = []
    received = 0

    while received < max_bytes:
        remaining = max_bytes - received

        try:
            chunk = await response.content.read(
                min(16 * 1024, remaining)
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise _ResponseReadError(
                exc,
                b"".join(chunks),
            ) from exc

        if not chunk:
            return b"".join(chunks), False, received

        chunks.append(chunk)
        received += len(chunk)

    content = b"".join(chunks)
    content_length = response.content_length

    if content_length is None:
        # Unknown-length response: only mark incomplete if EOF
        # has not been confirmed. Do not read an additional byte.
        exceeded = not response.content.at_eof()
    else:
        # A declared length equal to the consumed bytes is complete.
        exceeded = content_length != received

    return content, exceeded, received


async def _request_once(
    requested_url: str,
    max_bytes: int,
    deadline: float,
) -> NetworkResult:
    current_url = requested_url
    redirects: list[str] = []

    for redirect_number in range(config.MAX_REDIRECTS + 1):
        remaining = deadline - asyncio.get_running_loop().time()

        if remaining <= 0:
            raise asyncio.TimeoutError("Request budget exhausted.")

        normalized, hostname, port = _validate_url(current_url)

        addresses = await _resolve_public_ipv4(hostname, port)

        remaining = deadline - asyncio.get_running_loop().time()

        if remaining <= 0:
            raise asyncio.TimeoutError("Request budget exhausted.")

        resolver = _PinnedIPv4Resolver(addresses)

        connector = aiohttp.TCPConnector(
            resolver=resolver,
            family=socket.AF_INET,
            use_dns_cache=False,
            limit=1,
        )

        timeout = aiohttp.ClientTimeout(
            total=None,
            connect=min(config.TCP_CONNECT_TIMEOUT_SECONDS, remaining),
            sock_connect=min(config.TCP_CONNECT_TIMEOUT_SECONDS, remaining),
            sock_read=min(config.NETWORK_READ_TIMEOUT_SECONDS, remaining),
        )

        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                trust_env=config.TRUST_ENV_PROXY,
                auto_decompress=config.AUTO_DECOMPRESS,
                headers={
                    "Accept-Encoding": config.ACCEPT_ENCODING,
                    "User-Agent": "IPTV-Auto/1.0",
                },
                max_line_size=config.MAX_HTTP_HEADER_LINE_BYTES,
                max_field_size=config.MAX_HTTP_HEADER_LINE_BYTES,
                max_headers=config.MAX_HTTP_HEADERS_COUNT,
            ) as session:
                async with session.get(
                    normalized,
                    allow_redirects=False,
                    ssl=True,
                ) as response:
                    _check_headers(response)

                    remote_ip = _actual_remote_ip(response)

                    if remote_ip not in addresses:
                        raise OSError(
                            "Actual remote IP differs from validated DNS."
                        )

                    if response.status in _REDIRECT_STATUSES:
                        location = response.headers.get("Location")

                        if not location:
                            raise ValueError(
                                "Redirect response has no Location header."
                            )

                        if redirect_number >= config.MAX_REDIRECTS:
                            raise ValueError("Too many redirects.")

                        next_url = urljoin(normalized, location)
                        next_normalized, _, _ = _validate_url(next_url)

                        redirects.append(next_normalized)
                        current_url = next_normalized
                        continue

                    try:
                        content, exceeded, bytes_received = (
                            await _read_limited(response, max_bytes)
                        )
                    except _ResponseReadError as exc:
                        return _failure(
                            requested_url,
                            (
                                "Response read interrupted: "
                                f"{exc.cause_name}."
                            ),
                            content=exc.content,
                            bytes_received=exc.bytes_received,
                            status_code=response.status,
                            final_url=normalized,
                            remote_ip=remote_ip,
                            content_type=response.headers.get("Content-Type"),
                            redirects=tuple(redirects),
                        )

                    if exceeded:
                        return _failure(
                            requested_url,
                            "Response exceeded read limit.",
                            content=content,
                            bytes_received=bytes_received,
                            status_code=response.status,
                            final_url=normalized,
                            remote_ip=remote_ip,
                            content_type=response.headers.get("Content-Type"),
                            redirects=tuple(redirects),
                        )

                    return NetworkResult(
                        success=True,
                        requested_url=requested_url,
                        content=content,
                        final_url=normalized,
                        remote_ip=remote_ip,
                        status_code=response.status,
                        content_type=response.headers.get("Content-Type"),
                        bytes_received=bytes_received,
                        redirects=tuple(redirects),
                        error=None,
                    )
        finally:
            await connector.close()

    return _failure(
        requested_url,
        "Redirect processing failed.",
        redirects=tuple(redirects),
    )


async def request(
    url: str,
    max_bytes: int,
    *,
    timeout_seconds: Optional[float] = None,
) -> NetworkResult:
    """Perform one bounded IPv4-only GET request."""

    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool):
        return _failure(url, "max_bytes must be an integer.")

    if max_bytes <= 0:
        return _failure(url, "max_bytes must be positive.")

    if timeout_seconds is None:
        timeout_seconds = config.CANDIDATE_VALIDATION_BUDGET_SECONDS

    if timeout_seconds <= 0:
        return _failure(url, "timeout_seconds must be positive.")

    try:
        _validate_url(url)
    except (TypeError, ValueError) as exc:
        return _failure(url, str(exc))

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    attempts = config.MAX_NETWORK_RETRIES + 1

    for attempt in range(attempts):
        remaining = deadline - loop.time()

        if remaining <= 0:
            return _failure(url, "Request total budget exhausted.")

        try:
            return await asyncio.wait_for(
                _request_once(url, max_bytes, deadline),
                timeout=remaining,
            )
        except aiohttp.ClientSSLError:
            return _failure(url, "TLS verification failed.")
        except aiohttp.ClientResponseError as exc:
            message = str(exc.message).replace("\r", " ").replace("\n", " ")
            message = message.strip()[:200]

            error = f"HTTP response error: status={exc.status}"
            if message:
                error += f", message={message}"

            return _failure(
                url,
                error,
                status_code=exc.status,
            )
        except (ValueError, TypeError) as exc:
            return _failure(url, str(exc))
            return _failure(url, str(exc))
        except asyncio.TimeoutError:
            if attempt + 1 >= attempts:
                return _failure(url, "Network request timed out.")
        except aiohttp.ClientConnectionError as exc:
            if attempt + 1 >= attempts:
                return _failure(
                    url,
                    f"Connection error: {type(exc).__name__}",
                )
        except (aiohttp.ClientError, OSError) as exc:
            return _failure(
                url,
                f"Network request error: {type(exc).__name__}",
            )

    return _failure(url, "Network request failed.")
