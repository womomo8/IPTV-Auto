
"""Filter validated IPTV candidates and generate standard M3U content.

This module:
- Accepts only completed, passed validation results.
- Applies stable source-priority ordering.
- Deduplicates normalized stream URLs.
- Deduplicates channel identifiers.
- Generates standard M3U text.

It does not perform network requests, write files, or publish output.
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
    """Normalize text for channel identity comparison and group output."""
    if not isinstance(value, str):
        return ""

    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split())


def _clean_channel_display_name(value: Optional[str]) -> str:
    """Clean whitespace while preserving the original display characters."""
    if not isinstance(value, str):
        return ""

    return " ".join(value.split())


def _clean_tvg_id(value: Optional[str]) -> Optional[str]:
    """Trim and NFC-normalize a TVG identifier."""
    if not isinstance(value, str):
        return None

    normalized = unicodedata.normalize("NFC", value.strip())
    return normalized or None


def _comparison_text(value: str) -> str:
    """Build a case-insensitive channel comparison key."""
    return _clean_display_text(value).casefold()


def _attribute_value(value: str) -> str:
    """Make an M3U attribute safe for a quoted single-line value."""
    return (
        value
        .replace("\r", " ")
        .replace("\n", " ")
        .replace('"', "'")
    )


def _channel_display_name(candidate: Candidate) -> str:
    """Use the cleaned original channel name as the display name."""
    return _clean_channel_display_name(candidate.name)


def _candidate_priority(
    candidate: Candidate,
) -> tuple[int, int, int]:
    """Return stable source and item ordering."""
    priority = _SOURCE_PRIORITY.get(candidate.source_kind, 99)

    return (
        priority,
        candidate.source_order,
        candidate.item_order,
    )


def _normalize_candidate_url(
    candidate: Candidate,
) -> Optional[str]:
    """Normalize a candidate URL using the shared URL rules."""
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
    """Build an EXTINF line using the required attribute order."""
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

    safe_display_name = (
        display_name
        .replace("\r", " ")
        .replace("\n", " ")
    )

    return f"#EXTINF:-1 {attribute_text},{safe_display_name}"


def filter_candidates(
    validation_results: Sequence[ValidationResult],
) -> FilterResult:
    """Filter validated candidates and generate M3U content.

    Only results with completed=True and passed=True are considered.

    URL duplicates retain the highest-priority, earliest candidate.
    Channel duplicates use tvg-id, or channel name plus group.

    The returned content uses LF line endings and always starts
    with #EXTM3U, even when no valid channel remains.
    """
    if (
        not isinstance(validation_results, Sequence)
        or isinstance(
            validation_results,
            (str, bytes, bytearray),
        )
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

        if not display_name:
            continue

        normalized_url = _normalize_candidate_url(candidate)

        if normalized_url is None:
            continue

        # Address deduplication is performed before channel deduplication.
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

    # The final check prevents the last processing step from
    # crossing the filter budget unnoticed.
    if time.monotonic() >= deadline:
        raise TimeoutError("Filter stage budget exhausted.")

    return FilterResult(
        m3u_content="\n".join(output_lines) + "\n",
        channel_count=channel_count,
    )
