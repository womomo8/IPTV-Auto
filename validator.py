
"""Validate allocated IPTV candidates using the shared IPv4 network layer.

This module does not collect sources, parse subscriptions, allocate
candidate limits, or generate M3U files.

All HTTP requests are delegated to network.py.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Optional, Sequence
from urllib.parse import urljoin, urlsplit

import config
import network
from models import Candidate, NetworkResult, StreamType, ValidationResult


logger = logging.getLogger(__name__)

_PLAYLIST_TAG = "#EXTM3U"
_MASTER_TAG = "#EXT-X-STREAM-INF"

_REDIRECT_OR_HTTP_SUCCESS_MIN = 200
_HTTP_SUCCESS_MAX = 300

_VARIANT_ATTRIBUTE = re.compile(
    r'([A-Z0-9-]+)=("[^"]*"|[^,]*)'
)


def _http_ok(result: NetworkResult) -> bool:
    """Check network-layer success and HTTP status separately."""
    return (
        result.success
        and result.status_code is not None
        and _REDIRECT_OR_HTTP_SUCCESS_MIN
        <= result.status_code
        < _HTTP_SUCCESS_MAX
    )


def _has_ts_sync(data: bytes) -> bool:
    """Find five MPEG-TS sync bytes spaced exactly 188 bytes apart."""
    if not isinstance(data, bytes):
        return False

    for offset in range(min(187, len(data))):
        if all(
            offset + packet_index * 188 < len(data)
            and data[offset + packet_index * 188] == 0x47
            for packet_index in range(5)
        ):
            return True

    return False


def _is_hls_url(url: str) -> bool:
    """Recognize the conventional HLS playlist URL suffix."""
    try:
        return urlsplit(url).path.lower().endswith(".m3u8")
    except ValueError:
        return False


def _is_hls_content(result: NetworkResult) -> bool:
    """Recognize an HLS playlist by its body or response content type."""
    body = result.content.lstrip(b"\xef\xbb\xbf \t\r\n")

    if body.startswith(_PLAYLIST_TAG.encode("ascii")):
        return True

    content_type = (result.content_type or "").lower()

    return (
        "mpegurl" in content_type
        or "vnd.apple.mpegurl" in content_type
    )


async def _request(
    url: str,
    max_bytes: int,
    deadline: float,
) -> NetworkResult:
    """Call network.py with the remaining candidate budget."""
    remaining = deadline - time.monotonic()

    if remaining <= 0:
        raise asyncio.TimeoutError("Candidate validation budget exhausted.")

    return await network.request(
        url,
        max_bytes,
        timeout_seconds=remaining,
    )


def _playlist_text(result: NetworkResult) -> Optional[str]:
    """Decode a complete UTF-8 HLS playlist."""
    if not _http_ok(result):
        return None

    try:
        text = result.content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    if not lines or lines[0] != _PLAYLIST_TAG:
        return None

    return text


def _parse_attributes(value: str) -> dict[str, str]:
    """Parse an HLS attribute list, including quoted values."""
    attributes: dict[str, str] = {}

    for match in _VARIANT_ATTRIBUTE.finditer(value):
        key = match.group(1)
        item = match.group(2).strip()

        if item.startswith('"') and item.endswith('"'):
            item = item[1:-1]

        attributes[key] = item

    return attributes


def _check_unsupported_tags(lines: Sequence[str]) -> Optional[str]:
    """Reject encryption and media formats outside the supported scope."""
    for line in lines:
        if line.startswith("#EXT-X-SESSION-KEY"):
            return "HLS session keys are not supported."

        if line.startswith("#EXT-X-MAP"):
            return "HLS fMP4 initialization maps are not supported."

        if line.startswith("#EXT-X-KEY:"):
            attributes = _parse_attributes(
                line.partition(":")[2]
            )
            method = attributes.get("METHOD", "").upper()

            if method != "NONE":
                return "Encrypted HLS streams are not supported."

    return None


def _parse_master_variants(
    lines: Sequence[str],
) -> tuple[tuple[int, int, str], ...]:
    """Extract variants and sort by bandwidth, preserving tie order."""
    variants: list[tuple[int, int, str]] = []
    pending_bandwidth: Optional[int] = None

    for line_index, line in enumerate(lines):
        if line.startswith(_MASTER_TAG + ":"):
            attributes = _parse_attributes(
                line.partition(":")[2]
            )

            try:
                bandwidth = int(attributes.get("BANDWIDTH", "0"))
            except ValueError:
                bandwidth = 0

            pending_bandwidth = max(0, bandwidth)
            continue

        if line.startswith("#"):
            continue

        if pending_bandwidth is not None:
            variants.append(
                (pending_bandwidth, line_index, line)
            )
            pending_bandwidth = None

    variants.sort(key=lambda item: (-item[0], item[1]))

    return tuple(variants)


def _first_media_segment(
    lines: Sequence[str],
) -> Optional[str]:
    """Return the first media segment URI from a media playlist."""
    for line in lines:
        if not line or line.startswith("#"):
            continue

        path = urlsplit(line).path.lower()

        if path.endswith((".m4s", ".mp4", ".m4v", ".cmfv", ".cmfa")):
            return None

        return line

    return None


async def _fetch_playlist(
    url: str,
    deadline: float,
) -> tuple[Optional[NetworkResult], Optional[str]]:
    """Fetch and validate one HLS playlist within the shared deadline."""
    result = await _request(
        url,
        config.MAX_HLS_PLAYLIST_BYTES,
        deadline,
    )

    if not _http_ok(result):
        return None, result.error or "HLS playlist request failed."

    text = _playlist_text(result)

    if text is None:
        return None, "Invalid or non-UTF-8 HLS playlist."

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    unsupported = _check_unsupported_tags(lines)

    if unsupported:
        return None, unsupported

    return result, None


async def _validate_media_playlist(
    playlist_url: str,
    deadline: float,
) -> tuple[bool, Optional[str]]:
    """Fetch a media playlist and validate its first MPEG-TS segment."""
    playlist_result, error = await _fetch_playlist(
        playlist_url,
        deadline,
    )

    if playlist_result is None:
        return False, error

    playlist_text = _playlist_text(playlist_result)

    if playlist_text is None:
        return False, "Invalid media playlist."

    lines = [
        line.strip()
        for line in playlist_text.splitlines()
        if line.strip()
    ]

    if any(line.startswith(_MASTER_TAG + ":") for line in lines):
        return False, "Nested HLS master playlists are not supported."

    segment_uri = _first_media_segment(lines)

    if segment_uri is None:
        return False, "No supported MPEG-TS segment was found."

    base_url = playlist_result.final_url or playlist_url
    segment_url = urljoin(base_url, segment_uri)

    segment_result = await _request(
        segment_url,
        min(
            config.MAX_HLS_SEGMENT_BYTES,
            config.MAX_TS_VALIDATION_BYTES,
        ),
        deadline,
    )

    if not _http_ok(segment_result):
        return False, (
            segment_result.error or "HLS segment request failed."
        )

    if not _has_ts_sync(segment_result.content):
        return False, "HLS segment does not contain valid MPEG-TS sync."

    return True, None


async def _validate_hls(
    candidate_url: str,
    initial_result: Optional[NetworkResult],
    deadline: float,
) -> tuple[bool, Optional[str]]:
    """Validate a media playlist or one level of master playlist variants."""
    if initial_result is None:
        playlist_result, error = await _fetch_playlist(
            candidate_url,
            deadline,
        )
        if playlist_result is None:
            return False, error
    else:
        if not _http_ok(initial_result):
            return False, (
                initial_result.error or "HLS playlist request failed."
            )

        playlist_result = initial_result

        if _playlist_text(playlist_result) is None:
            return False, "Invalid or non-UTF-8 HLS playlist."

    playlist_text = _playlist_text(playlist_result)

    if playlist_text is None:
        return False, "Invalid HLS playlist."

    lines = [
        line.strip()
        for line in playlist_text.splitlines()
        if line.strip()
    ]

    unsupported = _check_unsupported_tags(lines)

    if unsupported:
        return False, unsupported

    playlist_url = playlist_result.final_url or candidate_url

    if any(line.startswith(_MASTER_TAG + ":") for line in lines):
        variants = _parse_master_variants(lines)

        if not variants:
            return False, "Master playlist contains no usable variants."

        last_error = "No HLS variant could be validated."

        for _, _, variant_uri in variants[
            :config.MAX_HLS_VARIANT_PLAYLISTS
        ]:
            if time.monotonic() >= deadline:
                raise asyncio.TimeoutError(
                    "Candidate validation budget exhausted."
                )

            variant_url = urljoin(playlist_url, variant_uri)

            passed, error = await _validate_media_playlist(
                variant_url,
                deadline,
            )

            if passed:
                return True, None

            last_error = error or last_error

        return False, last_error

    return await _validate_media_playlist(
        playlist_url,
        deadline,
    )


async def _validate_one(
    candidate: Candidate,
) -> ValidationResult:
    """Validate one candidate with a single shared eight-second budget."""
    deadline = (
        time.monotonic()
        + co
