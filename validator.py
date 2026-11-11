
"""Validate allocated IPTV candidates through the shared IPv4 network layer."""

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
_READ_LIMIT_ERROR = "Response exceeded read limit."


def _http_status_ok(result: NetworkResult) -> bool:
    return (
        result.status_code is not None
        and 200 <= result.status_code < 300
    )


def _http_ok(result: NetworkResult) -> bool:
    return result.success and _http_status_ok(result)


def _http_failure_reason(
    result: NetworkResult,
    fallback: str,
) -> str:
    """Preserve HTTP status details without duplicating existing status text."""
    status = result.status_code
    error = (result.error or "").strip()

    if status is not None and not 200 <= status < 300:
        if re.search(r"\bstatus\s*=\s*\d{3}\b", error, re.IGNORECASE):
            return error
        if error:
            return f"HTTP status {status}: {error}"
        return f"HTTP status {status}"

    return error or fallback


def _bounded_prefix_ok(result: NetworkResult) -> bool:
    """Accept a deliberately limited response prefix for TS inspection."""
    return (
        not result.success
        and result.error == _READ_LIMIT_ERROR
        and _http_status_ok(result)
        and bool(result.content)
    )


def _has_ts_sync(data: bytes) -> bool:
    """Find five MPEG-TS sync bytes at 188-byte intervals."""
    if not isinstance(data, bytes):
        return False

    for offset in range(min(187, len(data))):
        if all(
            offset + index * 188 < len(data)
            and data[offset + index * 188] == 0x47
            for index in range(5)
        ):
            return True

    return False


def _is_hls_url(url: str) -> bool:
    try:
        return urlsplit(url).path.lower().endswith(".m3u8")
    except ValueError:
        return False


def _is_hls_content(result: NetworkResult) -> bool:
    body = result.content.lstrip(b"\xef\xbb\xbf \t\r\n")

    if body.startswith(_PLAYLIST_TAG.encode("ascii")):
        return True

    content_type = (result.content_type or "").lower()
    return "mpegurl" in content_type


async def _request(
    url: str,
    max_bytes: int,
    deadline: float,
) -> NetworkResult:
    remaining = deadline - time.monotonic()

    if remaining <= 0:
        raise asyncio.TimeoutError(
            "Candidate validation budget exhausted."
        )

    return await network.request(
        url,
        max_bytes,
        timeout_seconds=remaining,
    )


def _playlist_text(result: NetworkResult) -> Optional[str]:
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
    attributes: dict[str, str] = {}
    pattern = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')

    for match in pattern.finditer(value):
        item = match.group(2).strip()

        if item.startswith('"') and item.endswith('"'):
            item = item[1:-1]

        attributes[match.group(1)] = item

    return attributes


def _check_unsupported_tags(
    lines: Sequence[str],
) -> Optional[str]:
    for line in lines:
        if line.startswith("#EXT-X-SESSION-KEY"):
            return "HLS session keys are not supported."

        if line.startswith("#EXT-X-MAP"):
            return "HLS fMP4 initialization maps are not supported."

        if line.startswith("#EXT-X-KEY:"):
            attributes = _parse_attributes(line.partition(":")[2])

            if attributes.get("METHOD", "").upper() != "NONE":
                return "Encrypted HLS streams are not supported."

    return None


def _parse_master_variants(
    lines: Sequence[str],
) -> tuple[tuple[int, int, str], ...]:
    variants: list[tuple[int, int, str]] = []
    pending_bandwidth: Optional[int] = None

    for line_index, line in enumerate(lines):
        if line.startswith(_MASTER_TAG + ":"):
            attributes = _parse_attributes(line.partition(":")[2])

            try:
                bandwidth = int(attributes.get("BANDWIDTH", "0"))
            except ValueError:
                bandwidth = 0

            pending_bandwidth = max(0, bandwidth)
            continue

        if line.startswith("#"):
            continue

        if pending_bandwidth is not None:
            variants.append((pending_bandwidth, line_index, line))
            pending_bandwidth = None

    variants.sort(key=lambda item: (-item[0], item[1]))
    return tuple(variants)


def _first_media_segment(lines: Sequence[str]) -> Optional[str]:
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
    result = await _request(
        url,
        config.MAX_HLS_PLAYLIST_BYTES,
        deadline,
    )

    if not _http_ok(result):
        return None, _http_failure_reason(
            result,
            "HLS playlist request failed.",
        )

    if _playlist_text(result) is None:
        return None, "Invalid or non-UTF-8 HLS playlist."

    lines = [
        line.strip()
        for line in result.content.decode("utf-8-sig").splitlines()
        if line.strip()
    ]

    unsupported = _check_unsupported_tags(lines)

    if unsupported:
        return None, unsupported

    return result, None


async def _validate_media_playlist(
    playlist_url: str,
    deadline: float,
    *,
    existing_result: Optional[NetworkResult] = None,
) -> tuple[bool, Optional[str]]:
    if existing_result is None:
        playlist_result, error = await _fetch_playlist(
            playlist_url,
            deadline,
        )

        if playlist_result is None:
            return False, error
    else:
        playlist_result = existing_result

    text = _playlist_text(playlist_result)

    if text is None:
        return False, "Invalid media playlist."

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    unsupported = _check_unsupported_tags(lines)

    if unsupported:
        return False, unsupported

    if any(line.startswith(_MASTER_TAG + ":") for line in lines):
        return False, "Nested HLS master playlists are not supported."

    segment_uri = _first_media_segment(lines)

    if segment_uri is None:
        return False, "No supported MPEG-TS segment was found."

    base_url = playlist_result.final_url or playlist_url
    segment_url = urljoin(base_url, segment_uri)

    # TS synchronization needs at most 4KB. This is within the
    # configured 64KB HLS segment upper limit.
    segment_result = await _request(
        segment_url,
        min(
            config.MAX_HLS_SEGMENT_BYTES,
            config.MAX_TS_VALIDATION_BYTES,
        ),
        deadline,
    )

    if not (
        _http_ok(segment_result)
        or _bounded_prefix_ok(segment_result)
    ):
        return False, _http_failure_reason(
            segment_result,
            "HLS segment request failed.",
        )

    if not _has_ts_sync(segment_result.content):
        return False, "HLS segment does not contain valid MPEG-TS sync."

    return True, None


async def _validate_hls(
    candidate_url: str,
    initial_result: NetworkResult,
    deadline: float,
) -> tuple[bool, Optional[str]]:
    if not _http_ok(initial_result):
        return False, _http_failure_reason(
            initial_result,
            "HLS playlist request failed.",
        )

    text = _playlist_text(initial_result)

    if text is None:
        return False, "Invalid or non-UTF-8 HLS playlist."

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    unsupported = _check_unsupported_tags(lines)

    if unsupported:
        return False, unsupported

    playlist_url = initial_result.final_url or candidate_url

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

    # Reuse the playlist already downloaded; do not fetch it twice.
    return await _validate_media_playlist(
        playlist_url,
        deadline,
        existing_result=initial_result,
    )


async def _validate_one(candidate: Candidate) -> ValidationResult:
    deadline = (
        time.monotonic()
        + config.CANDIDATE_VALIDATION_BUDGET_SECONDS
    )

    try:
        if _is_hls_url(candidate.url):
            initial = await _request(
                candidate.url,
                config.MAX_HLS_PLAYLIST_BYTES,
                deadline,
            )

            passed, reason = await _validate_hls(
                candidate.url,
                initial,
                deadline,
            )

            return ValidationResult(
                candidate=candidate,
                passed=passed,
                stream_type=StreamType.HLS,
                completed=True,
                reason=reason,
            )

        initial = await _request(
            candidate.url,
            config.MAX_TS_VALIDATION_BYTES,
            deadline,
        )

        if _is_hls_content(initial):
            # Retry with the playlist size limit if the small initial
            # probe identified HLS but was cut off by the 4KB limit.
            if (
                not _http_ok(initial)
                and initial.content.lstrip(
                    b"\xef\xbb\xbf \t\r\n"
                ).startswith(b"#EXTM3U")
            ):
                initial = await _request(
                    initial.final_url or candidate.url,
                    config.MAX_HLS_PLAYLIST_BYTES,
                    deadline,
                )

            passed, reason = await _validate_hls(
                candidate.url,
                initial,
                deadline,
            )

            return ValidationResult(
                candidate=candidate,
                passed=passed,
                stream_type=StreamType.HLS,
                completed=True,
                reason=reason,
            )

        if not (
            _http_ok(initial)
            or _bounded_prefix_ok(initial)
        ):
            if time.monotonic() >= deadline:
                raise asyncio.TimeoutError()

            return ValidationResult(
                candidate=candidate,
                passed=False,
                stream_type=StreamType.TS,
                completed=True,
                reason=initial.error or (
                    f"HTTP request failed: {initial.status_code}"
                ),
            )

        passed = _has_ts_sync(initial.content)

        return ValidationResult(
            candidate=candidate,
            passed=passed,
            stream_type=StreamType.TS,
            completed=True,
            reason=None if passed else "MPEG-TS sync check failed.",
        )

    except asyncio.TimeoutError:
        return ValidationResult(
            candidate=candidate,
            passed=False,
            stream_type=StreamType.UNKNOWN,
            completed=False,
            reason="Candidate validation budget exhausted.",
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception(
            "Unexpected validation error for candidate: %s",
            candidate.url,
        )

        return ValidationResult(
            candidate=candidate,
            passed=False,
            stream_type=StreamType.UNKNOWN,
            completed=True,
            reason=f"Validation error: {type(exc).__name__}",
        )


async def validate_candidates(
    candidates: Sequence[Candidate],
) -> tuple[ValidationResult, ...]:
    """Validate allocated candidates in stable input order."""
    if (
        not isinstance(candidates, Sequence)
        or isinstance(candidates, (str, bytes, bytearray))
    ):
        raise TypeError("candidates must be a sequence of Candidate objects")

    if len(candidates) > config.MAX_CANDIDATES_TOTAL:
        raise ValueError("Candidate count exceeds the configured global limit.")

    if any(not isinstance(item, Candidate) for item in candidates):
        raise TypeError("Every item must be a Candidate")

    if not candidates:
        return ()

    if config.MAX_CONCURRENT_VALIDATIONS <= 0:
        raise ValueError("MAX_CONCURRENT_VALIDATIONS must be positive.")

    if config.VALIDATION_WAITING_QUEUE_LIMIT <= 0:
        raise ValueError("VALIDATION_WAITING_QUEUE_LIMIT must be positive.")

    if config.DETECTION_BUDGET_SECONDS <= 0:
        raise ValueError("DETECTION_BUDGET_SECONDS must be positive.")

    results: list[Optional[ValidationResult]] = [
        None for _ in candidates
    ]

    queue: asyncio.Queue[Optional[tuple[int, Candidate]]] = asyncio.Queue(
        maxsize=config.VALIDATION_WAITING_QUEUE_LIMIT
    )

    async def producer() -> None:
        for index, candidate in enumerate(candidates):
            await queue.put((index, candidate))

        for _ in range(config.MAX_CONCURRENT_VALIDATIONS):
            await queue.put(None)

    async def worker() -> None:
        while True:
            item = await queue.get()

            if item is None:
                return

            index, candidate = item

            try:
                results[index] = await asyncio.wait_for(
                    _validate_one(candidate),
                    timeout=config.CANDIDATE_VALIDATION_BUDGET_SECONDS,
                )
            except asyncio.TimeoutError:
                results[index] = ValidationResult(
                    candidate=candidate,
                    passed=False,
                    stream_type=StreamType.UNKNOWN,
                    completed=False,
                    reason="Candidate validation budget exhausted.",
                )

    workers = [
        asyncio.create_task(worker())
        for _ in range(config.MAX_CONCURRENT_VALIDATIONS)
    ]
    producer_task = asyncio.create_task(producer())

    # Keep a reference to the aggregate Future so its cancellation
    # exception can be explicitly retrieved during cleanup.
    task_group = asyncio.gather(producer_task, *workers)

    try:
        await asyncio.wait_for(
            task_group,
            timeout=config.DETECTION_BUDGET_SECONDS,
        )
    except asyncio.TimeoutError:
        try:
            await task_group
        except asyncio.CancelledError:
            pass

        producer_task.cancel()

        for task in workers:
            task.cancel()

        await asyncio.gather(
            producer_task,
            *workers,
            return_exceptions=True,
        )
    except asyncio.CancelledError:
        try:
            await task_group
        except asyncio.CancelledError:
            pass

        producer_task.cancel()

        for task in workers:
            task.cancel()

        await asyncio.gather(
            producer_task,
            *workers,
            return_exceptions=True,
        )
        raise

    for index, candidate in enumerate(candidates):
        if results[index] is None:
            results[index] = ValidationResult(
                candidate=candidate,
                passed=False,
                stream_type=StreamType.UNKNOWN,
                completed=False,
                reason="Detection stage budget exhausted.",
            )

    return tuple(
        result for result in results
        if result is not None
    )
