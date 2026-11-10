
"""Source management for the IPTV automation pipeline.

This module:
- Reads and validates manually configured sources.
- Normalizes and deduplicates source URLs.
- Accepts automatic index entry URLs supplied by the caller.
- Parses already-downloaded index content.

It does not perform network requests or download files.
"""

import logging
from typing import Iterable, List, Set, Tuple
from urllib.parse import urlsplit, urlunsplit

import config
from models import (
    DownloadResult,
    IndexParseResult,
    SourceKind,
    SourceRecord,
)


logger = logging.getLogger(__name__)


def normalize_source_url(value: str) -> str:
    """Normalize and validate an HTTP/HTTPS source URL.

    Raises:
        ValueError: If the input is not a valid supported URL.
    """
    if not isinstance(value, str):
        raise ValueError("URL must be a string")

    raw_url = value.strip()
    if not raw_url:
        raise ValueError("URL is empty")

    if any(ord(char) <= 32 or ord(char) == 127 for char in raw_url):
        raise ValueError("URL contains whitespace or control characters")

    try:
        parts = urlsplit(raw_url)
    except ValueError as exc:
        raise ValueError(f"Invalid URL: {exc}") from exc

    scheme = parts.scheme.lower()
    if scheme not in config.ALLOWED_URL_SCHEMES:
        raise ValueError("Only HTTP and HTTPS URLs are allowed")

    if not parts.netloc:
        raise ValueError("URL host is missing")

    if parts.username is not None or parts.password is not None:
        raise ValueError("URL userinfo is not allowed")

    try:
        hostname = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise ValueError(f"Invalid host or port: {exc}") from exc

    if not hostname:
        raise ValueError("URL host is invalid")

    if port is not None:
        if not config.MIN_TCP_PORT <= port <= config.MAX_TCP_PORT:
            raise ValueError("URL port must be between 1 and 65535")

    hostname = hostname.lower()

    # Preserve IPv6 URL bracket syntax. Network-layer policy is enforced
    # later by network.py; this function does not perform DNS checks.
    if ":" in hostname and not hostname.startswith("["):
        normalized_host = f"[{hostname}]"
    else:
        normalized_host = hostname

    if port is not None:
        is_default_port = (
            (scheme == "http" and port == 80)
            or (scheme == "https" and port == 443)
        )
        if not is_default_port:
            normalized_host = f"{normalized_host}:{port}"

    path = parts.path or "/"

    return urlunsplit(
        (
            scheme,
            normalized_host,
            path,
            parts.query,
            "",
        )
    )


def _append_source(
    output: List[SourceRecord],
    seen_urls: Set[str],
    raw_url: str,
    kind: SourceKind,
    order: int,
) -> None:
    """Validate, normalize, and append one source if it is unique."""
    try:
        normalized_url = normalize_source_url(raw_url)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "Skipping invalid %s source at position %s: %s",
            kind.value,
            order,
            exc,
        )
        return

    if normalized_url in seen_urls:
        logger.info(
            "Skipping duplicate %s source: %s",
            kind.value,
            normalized_url,
        )
        return

    seen_urls.add(normalized_url)
    output.append(
        SourceRecord(
            url=normalized_url,
            kind=kind,
            order=order,
        )
    )


def build_source_list(
    auto_index_urls: Iterable[str] = (),
) -> Tuple[SourceRecord, ...]:
    """Build the normalized, globally deduplicated source list.

    Priority follows MASTER_PLAN.md:
    1. Manual single-stream URLs.
    2. Manual subscription sources.
    3. Automatic index entry URLs.

    The caller supplies automatic index URLs. This module does not
    invent or download automatic index addresses.
    """
    output: List[SourceRecord] = []
    seen_urls: Set[str] = set()
    order = 0

    source_groups = (
        (
            SourceKind.MANUAL_STREAM,
            config.MANUAL_STREAM_URLS,
        ),
        (
            SourceKind.MANUAL_SUBSCRIPTION,
            config.MANUAL_SUBSCRIPTION_SOURCES,
        ),
        (
            SourceKind.AUTO_INDEX,
            auto_index_urls,
        ),
    )

    for kind, raw_urls in source_groups:
        if raw_urls is None:
            logger.warning("Source list for %s is None", kind.value)
            continue

        try:
            iterator = iter(raw_urls)
        except TypeError:
            logger.warning("Source list for %s is not iterable", kind.value)
            continue

        for raw_url in iterator:
            order += 1
            _append_source(
                output=output,
                seen_urls=seen_urls,
                raw_url=raw_url,
                kind=kind,
                order=order,
            )

    return tuple(output)


def parse_index_download(
    result: DownloadResult,
) -> IndexParseResult:
    """Parse one successfully downloaded automatic index.

    The index format is UTF-8 plain text, one absolute HTTP/HTTPS URL
    per line. Downloading and network validation belong to other modules.
    """
    if not isinstance(result, DownloadResult):
        raise TypeError("result must be a DownloadResult")

    if result.source.kind != SourceKind.AUTO_INDEX:
        raise ValueError("DownloadResult source must have kind AUTO_INDEX")

    messages: List[str] = []

    def failed(message: str, invalid_count: int = 0) -> IndexParseResult:
        messages.append(message)
        logger.warning(
            "Index parsing failed for %s: %s",
            result.source.url,
            message,
        )
        return IndexParseResult(
            index_source=result.source,
            sources=(),
            invalid_count=invalid_count,
            messages=tuple(messages),
        )

    if not result.success:
        return failed(
            result.error or "Index download was not successful"
        )

    if result.truncated:
        return failed("Index download was truncated")

    if len(result.content) > config.MAX_INDEX_BYTES:
        return failed("Index content exceeds the configured size limit")

    try:
        content = result.content.decode("utf-8")
    except UnicodeDecodeError as exc:
        return failed(f"Index content is not valid UTF-8: {exc}")

    parsed_sources: List[SourceRecord] = []
    seen_urls: Set[str] = set()
    invalid_count = 0

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        if not raw_line.strip():
            continue

        # Only full-line comments are ignored.
        if raw_line.startswith("#"):
            continue

        raw_url = raw_line.strip()

        try:
            normalized_url = normalize_source_url(raw_url)
        except (TypeError, ValueError) as exc:
            invalid_count += 1
            message = f"Line {line_number}: {exc}"
            messages.append(message)
            logger.warning(
                "Invalid URL in index %s: %s",
                result.source.url,
                message,
            )
            continue

        if normalized_url in seen_urls:
            messages.append(
                f"Line {line_number}: duplicate URL skipped"
            )
            continue

        seen_urls.add(normalized_url)
        parsed_sources.append(
            SourceRecord(
                url=normalized_url,
                kind=SourceKind.AUTO_SUBSCRIPTION,
                order=line_number,
            )
        )

    return IndexParseResult(
        index_source=result.source,
        sources=tuple(parsed_sources),
        invalid_count=invalid_count,
        messages=tuple(messages),
    )
