
"""Filter validated IPTV candidates and generate standard M3U content.

Responsibilities:
- Accept only completed, passed validation results.
- Apply stable source-priority ordering.
- Deduplicate normalized stream URLs.
- Deduplicate channel identifiers.
- Generate UTF-8-ready M3U text with LF line endings.

This module does not perform network requests, write files, or publish
the generated subscription.
"""

from __future__ import annotations

import time
import unicodedata
from typing import Optional, Sequence

import config
import sources
from models import (
    Candidate,
    FilterResult,
    SourceKind,
    ValidationResult,
)


_SOURCE_PRIORITY = {
    SourceKind.MANUAL_STREAM: 0,
    SourceKind.MANUAL_SUBSCRIPTION: 1,
    SourceKind.AUTO_SUBSCRIPTION: 2,
}


def _clean_display_text(value: Optional[str]) -> str:
    """Normalize display text while preserving its original casing."""
    if not isinstance(value, str):
        return ""

    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split())


def _clean_tvg_id(value: Optional[str]) -> Optional[str]:
    """Trim and NFC-normalize a TVG identifier."""
    if not isinstance(value, str):
        return None

    normalized = unicodedata.normalize("NFC", value.strip())

    return normalized or None


def _comparison_text(value: str) -> str:
    """Create a case-insensitive comparison key for channel text."""
    return _clean_display_text(value).casefold()


def _attribute_value(value: str) -> str:
    """Make an M3U attribute safe for a single-line quoted value."""
    return (
        value
        .replace("\r", " ")
        .replace("\n", " ")
        .replace('"', "'")
    )


def _channel_display_name(candidate: Candidate) -> str:
    """Choose the display name, preferring the explicit tvg-name."""
    tvg_name = _clean_display_text(candidate.tvg_name)

    if tvg_name:
        return tvg_name

    return _clean_display_text(candidate.name)


def _candidate_priority(candidate: Candidate) -> tuple[int, int, int]:
    """Return stable source and item ordering."""
    priority = _SOURCE_PRIORITY.get(candidate.source_kind, 99)

    return (
        priority,
        candidate.source_order,
        candidate.item_order,
    )


def _normalize_candidate_url(candidate: Candidate) -> Optional[str]:
    """Normalize a candidate URL using the shared source URL rules."""
    try:
        return sources.normalize_source_url(candidate.url)
    except (TypeError, ValueError):
        return None


def _channel_key(
    candidate: Candidate,
    display_name: str,
) -> tuple[str, ...]:
    """Build the exact channel deduplication key."""
    tvg_id = _clean_tvg_id(candidate.tvg_id)

    if tvg_id is not None:
        return ("id", tvg_id)

    group = _clean_display_text(candidate.group_title or "")

    return (
        "name",
        _comparison_text(display_name),
        _comparison_text(group),
    )


def _build_extinf(
    candidate: Candidate,
    display_name: str,
) -> str:
    """Build one EXTINF line with the required attribute order."""
    attributes: list[str] = []

    tvg_id = _clean_tvg_id(candidate.tvg_id)

    if tvg_id is not None:
        attributes.append(
            f'tvg-id="{_attribute_value(tvg_id)}"'
        )

    attributes.append(
        f'tvg-name="{_attribute_value(display_name)}"'
    )

    group = _clean_display_text(candidate.group_title or "")

    if group:
        attributes.append(
            f'group-title="{_attribute_value(group)}"'
        )

    attribute_text = " ".join(attributes)

    # The channel name is kept after the first comma. Commas inside
    # channel names are intentionally preserved.
    safe_display_name = (
        display_name
        .replace("\r", " ")
        .replace("\n", " ")
    )

    return f"#EXTINF:-1 {attribute_text},{safe_display_name}"


def filter_candidates(
    validation_results: Sequence[ValidationResult],
) -> FilterResult:
    """Filter validated candidates and return generated M3U content.

    Only results with both completed=True and passed=True are considered.

    Duplicate URLs keep the highest-priority, earliest candidate.
    Channel duplicates are then removed using tvg-id or name+group.

    The returned M3U content always uses LF line endings and starts
    with #EXTM3U, including when no valid channel remains.
    """
    if (
        not isinstance(validation_results, Sequence)
        or isinstance(validation_results, (str, bytes, bytearray))
    ):
        raise TypeError(
            "validation_results must be a sequence of ValidationResult objects"
        )

    if len(validation_results) > config.MAX_CANDIDATES_TOTAL:
        raise ValueError(
            "Validation result count exceeds the configured global limit."
        )

    if any(
        not isinstance(result, ValidationResult)
        for result in validation_results
    ):
        raise TypeError(
            "Every item must be a ValidationResult."
        )

    if config.FILTER_BUDGET_SECONDS <= 0:
        raise ValueError("FILTER_BUDGET_SECONDS must be positive.")

    deadline = time.monotonic() + config.FILTER_BUDGET_SECONDS

    # Preserve original index as the final tie-breaker so ordering is
    # deterministic even if two candidates share all ordering fields.
    eligible: list[tuple[int, Candidate]] = []

    for index, result in enumerate(validation_results):
        if time.monotonic() >= deadline:
            raise TimeoutError("Filter stage budget exhausted.")

        if not result.completed or not result.passed:
            continue

        eligible.append((index, result.candidate))

    eligible.sort(
        key=lambda item: (
            *_candidate_priority(item[1]),
            item[0],
        )
    )

    seen_urls: set[str] = set()
    seen_channels: set[tuple[str, ...]] = set()

    output_lines = ["#EXTM3U"]
    channel_count = 0

    for _, candidate in eligible:
        if time.monotonic() >= deadline:
            raise TimeoutError("Filter stage budget exhausted.")

        display_name = _channel_display_name(candidate)

        # A channel without a usable display name is never emitted.
        if not display_name:
            continue

        normalized_url = _normalize_candidate_url(candidate)

        if normalized_url is None:
            continue

        # Address deduplication takes place before channel deduplication.
        if normalized_url in seen_urls:
            continue

        seen_urls.add(normalized_url)

        channel_key = _channel_key(candidate, display_name)

        if channel_key in seen_channels:
            continue

        seen_channels.add(channel_key)

        output_lines.append(
            _build_extinf(candidate, display_name)
        )
        output_lines.append(normalized_url)

        channel_count += 1

    return FilterResult(
        m3u_content="\n".join(output_lines) + "\n",
        channel_count=channel_count,
    )
