
"""Normalize subscription data and allocate candidate limits.

This module parses downloaded M3U subscriptions, normalizes candidate
URLs, removes duplicates, and allocates candidate limits in stable
source-priority order.

All shared data structures come from models.py.
URL normalization is delegated to sources.py.
This module performs no network requests.
"""

from __future__ import annotations

import logging
import re
import time
from typing import List, Optional, Sequence, Set, Tuple
from urllib.parse import urlsplit

import config
import sources
from models import Candidate, DownloadResult, SourceKind


logger = logging.getLogger(__name__)


_ATTRIBUTE_PATTERN = re.compile(
    r"""([A-Za-z0-9_-]+)\s*=\s*
    (?:"([^"]*)"|'([^']*)'|([^\s]+))""",
    re.VERBOSE,
)


def _check_budget(deadline: float) -> None:
    """Stop normalization immediately when its stage budget expires."""
    if time.monotonic() >= deadline:
        raise TimeoutError("Normalization stage budget exhausted.")


def _log_invalid(message: str, *args: object) -> None:
    """Log an invalid subscription record without stopping the run."""
    logger.warning(message, *args)


def _split_extinf(line: str) -> Optional[Tuple[str, str]]:
    """Split an EXTINF line at the first comma outside quoted values."""
    if not line.startswith("#EXTINF:"):
        return None

    content = line[len("#EXTINF:"):]
    quote: Optional[str] = None

    for index, character in enumerate(content):
        if quote is not None:
            if character == quote:
                quote = None
            continue

        if character in ('"', "'"):
            quote = character
        elif character == ",":
            return content[:index], content[index + 1:]

    return None


def _parse_extinf_attributes(value: str) -> dict[str, str]:
    """Read supported EXTINF attributes and ignore unknown attributes."""
    attributes: dict[str, str] = {}

    for match in _ATTRIBUTE_PATTERN.finditer(value):
        key = match.group(1).lower()

        if match.group(2) is not None:
            item = match.group(2)
        elif match.group(3) is not None:
            item = match.group(3)
        else:
            item = match.group(4) or ""

        if key in ("tvg-id", "tvg-name", "group-title"):
            attributes[key] = item.strip()

    return attributes


def _parse_subscription(
    result: DownloadResult,
    deadline: float,
) -> Tuple[Candidate, ...]:
    """Parse one complete downloaded M3U subscription."""
    source = result.source

    if source.kind not in (
        SourceKind.MANUAL_SUBSCRIPTION,
        SourceKind.AUTO_SUBSCRIPTION,
    ):
        return ()

    if not result.success:
        _log_invalid(
            "Skipping unsuccessful subscription download: %s",
            source.url,
        )
        return ()

    if result.truncated:
        _log_invalid(
            "Skipping incomplete subscription download: %s",
            source.url,
        )
        return ()

    if not isinstance(result.content, bytes):
        _log_invalid(
            "Skipping subscription with invalid content type: %s",
            source.url,
        )
        return ()

    candidates: List[Candidate] = []
    pending: Optional[Tuple[dict[str, str], str, int]] = None
    current_group = ""
    item_order = 0

    for line_number, raw_line in enumerate(
        result.content.splitlines(),
        start=1,
    ):
        _check_budget(deadline)

        try:
            line = raw_line.decode("utf-8").strip()
        except UnicodeDecodeError:
            _log_invalid(
                "Invalid UTF-8 line in %s at line %d",
                source.url,
                line_number,
            )
            continue

        if not line:
            continue

        if line == "#EXTM3U":
            continue

        if line.startswith("#EXTGRP:"):
            group_value = line[len("#EXTGRP:"):].strip()
            if group_value:
                current_group = group_value
            continue

        if line.startswith("#EXTINF:"):
            if pending is not None:
                _log_invalid(
                    "EXTINF record has no URL in %s before line %d",
                    source.url,
                    line_number,
                )

            item_order += 1
            parts = _split_extinf(line)

            if parts is None:
                pending = None
                _log_invalid(
                    "Invalid EXTINF record in %s at line %d",
                    source.url,
                    line_number,
                )
                continue

            attribute_text, channel_name = parts
            channel_name = channel_name.strip()

            if not channel_name:
                pending = None
                _log_invalid(
                    "Missing channel name in %s at line %d",
                    source.url,
                    line_number,
                )
                continue

            attributes = _parse_extinf_attributes(attribute_text)
            pending = (attributes, channel_name, item_order)
            continue

        if line.startswith("#"):
            continue

        if pending is None:
            _log_invalid(
                "Ignoring M3U line without EXTINF in %s at line %d",
                source.url,
                line_number,
            )
            continue

        attributes, channel_name, candidate_order = pending
        pending = None

        try:
            normalized_url = sources.normalize_source_url(line)
        except (TypeError, ValueError) as exc:
            _log_invalid(
                "Invalid stream URL in %s at line %d: %s",
                source.url,
                line_number,
                exc,
            )
            continue

        group_title = attributes.get("group-title", "")
        if not group_title:
            group_title = current_group

        candidates.append(
            Candidate(
                url=normalized_url,
                name=channel_name,
                source_kind=source.kind,
                source_order=source.order,
                item_order=candidate_order,
                tvg_id=attributes.get("tvg-id") or None,
                tvg_name=attributes.get("tvg-name") or None,
                group_title=group_title or None,
                source_url=source.url,
            )
        )

    _check_budget(deadline)

    if pending is not None:
        _log_invalid(
            "Final EXTINF record has no URL in %s",
            source.url,
        )

    return tuple(candidates)


def _manual_stream_candidates(
    urls: Sequence[str],
    deadline: float,
) -> Tuple[Candidate, ...]:
    """Convert configured manual stream URLs into candidates."""
    candidates: List[Candidate] = []

    for index, raw_url in enumerate(urls):
        _check_budget(deadline)

        if not isinstance(raw_url, str):
            _log_invalid(
                "Ignoring manual stream URL with invalid type at index %d",
                index,
            )
            continue

        try:
            normalized_url = sources.normalize_source_url(raw_url)
        except (TypeError, ValueError) as exc:
            _log_invalid(
                "Ignoring invalid manual stream URL at index %d: %s",
                index,
                exc,
            )
            continue

        try:
            hostname = urlsplit(normalized_url).hostname
        except ValueError:
            hostname = None

        channel_name = hostname or normalized_url

        candidates.append(
            Candidate(
                url=normalized_url,
                name=channel_name,
                source_kind=SourceKind.MANUAL_STREAM,
                source_order=index,
                item_order=index,
                tvg_id=None,
                tvg_name=None,
                group_title=None,
                source_url=None,
            )
        )

    return tuple(candidates)


def normalize_candidates(
    download_results: Sequence[DownloadResult],
    *,
    manual_stream_urls: Optional[Sequence[str]] = None,
) -> Tuple[Candidate, ...]:
    """Parse, normalize, deduplicate, and allocate candidate limits.

    Candidate order is always:
    1. Manual single-stream URLs in configuration order.
    2. Manual subscription sources in source order.
    3. Automatic subscription sources in source order.

    Duplicate URLs do not consume candidate limits.
    Subscription sources are limited to MAX_CANDIDATES_PER_SOURCE.
    All retained candidates share MAX_CANDIDATES_TOTAL.

    The complete normalization operation shares one stage deadline.
    """
    if (
        not isinstance(download_results, Sequence)
        or isinstance(download_results, (str, bytes, bytearray))
    ):
        raise TypeError("download_results must be a sequence")

    for result in download_results:
        if not isinstance(result, DownloadResult):
            raise TypeError(
                "Every download result must be a DownloadResult"
            )

    if manual_stream_urls is None:
        manual_stream_urls = config.MANUAL_STREAM_URLS

    if (
        not isinstance(manual_stream_urls, Sequence)
        or isinstance(manual_stream_urls, (str, bytes, bytearray))
    ):
        raise TypeError("manual_stream_urls must be a sequence of URLs")

    if config.MAX_CANDIDATES_PER_SOURCE <= 0:
        raise ValueError("MAX_CANDIDATES_PER_SOURCE must be positive")

    if config.MAX_CANDIDATES_TOTAL <= 0:
        raise ValueError("MAX_CANDIDATES_TOTAL must be positive")

    if config.NORMALIZATION_BUDGET_SECONDS <= 0:
        raise ValueError("NORMALIZATION_BUDGET_SECONDS must be positive")

    deadline = (
        time.monotonic() + config.NORMALIZATION_BUDGET_SECONDS
    )

    _check_budget(deadline)

    ordered_results = sorted(
        enumerate(download_results),
        key=lambda item: (
            0
            if item[1].source.kind == SourceKind.MANUAL_SUBSCRIPTION
            else 1
            if item[1].source.kind == SourceKind.AUTO_SUBSCRIPTION
            else 2,
            item[1].source.order,
            item[0],
        ),
    )

    _check_budget(deadline)

    retained: List[Candidate] = []
    seen_urls: Set[str] = set()
    source_counts: dict[Tuple[SourceKind, int, str], int] = {}

    # Manual single-stream URLs have the highest priority.
    for candidate in _manual_stream_candidates(
        manual_stream_urls,
        deadline,
    ):
        _check_budget(deadline)

        if candidate.url in seen_urls:
            continue

        if len(retained) >= config.MAX_CANDIDATES_TOTAL:
            return tuple(retained)

        seen_urls.add(candidate.url)
        retained.append(candidate)

    # Subscription candidates are processed in stable source order.
    for _, result in ordered_results:
        _check_budget(deadline)

        for candidate in _parse_subscription(result, deadline):
            _check_budget(deadline)

            if candidate.url in seen_urls:
                continue

            if len(retained) >= config.MAX_CANDIDATES_TOTAL:
                return tuple(retained)

            source_key = (
                candidate.source_kind,
                candidate.source_order,
                candidate.source_url or "",
            )

            current_count = source_counts.get(source_key, 0)

            if current_count >= config.MAX_CANDIDATES_PER_SOURCE:
                continue

            seen_urls.add(candidate.url)
            retained.append(candidate)
            source_counts[source_key] = current_count + 1

    _check_budget(deadline)

    return tuple(retained)
