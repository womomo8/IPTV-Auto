
"""Normalize subscription data and allocate candidate limits.

Supports standard M3U and channel TXT subscriptions.
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

_M3U_MARKERS = (b"#EXTM3U", b"#EXTINF:", b"#EXTGRP:")


def _check_budget(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("Normalization stage budget exhausted.")


def _log_invalid(message: str, *args: object) -> None:
    logger.warning(message, *args)


def _split_extinf(line: str) -> Optional[Tuple[str, str]]:
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


def _is_m3u(content: bytes) -> bool:
    return any(marker in content for marker in _M3U_MARKERS)


def _decode_txt(content: bytes) -> Optional[str]:
    """Decode TXT strictly: UTF-8-SIG first, then GB18030."""
    try:
        decoded = content.decode("utf-8-sig", errors="strict")
        logger.info("Channel TXT decoded using UTF-8-SIG")
        return decoded
    except UnicodeDecodeError:
        pass

    try:
        decoded = content.decode("gb18030", errors="strict")
        logger.info("Channel TXT decoded using GB18030")
        return decoded
    except UnicodeDecodeError as exc:
        _log_invalid("Channel TXT decoding failed: %s", exc)
        return None


def _looks_like_txt(content: str) -> bool:
    for raw_line in content.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("//"):
            continue

        if line.endswith(",#genre#") or line.endswith(",#group#"):
            return True

        if "," in line:
            _, value = line.split(",", 1)
            if value.strip().lower().startswith(("http://", "https://")):
                return True

    return False


def _parse_m3u_subscription(
    result: DownloadResult,
    deadline: float,
) -> Tuple[Candidate, ...]:
    """Parse M3U using the original UTF-8-only line behavior."""
    source = result.source
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


def _parse_txt_subscription(
    result: DownloadResult,
    deadline: float,
) -> Tuple[Candidate, ...]:
    """Parse channel TXT records and inherit the current genre."""
    source = result.source
    decoded = _decode_txt(result.content)

    if decoded is None:
        _log_invalid("Skipping undecodable channel TXT: %s", source.url)
        return ()

    if not _looks_like_txt(decoded):
        _log_invalid("Unrecognized subscription format: %s", source.url)
        return ()

    candidates: List[Candidate] = []
    current_group = ""
    item_order = 0

    for line_number, raw_line in enumerate(decoded.splitlines(), start=1):
        _check_budget(deadline)
        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("//"):
            continue

        if line.endswith(",#group#"):
            continue

        if line.endswith(",#genre#"):
            group_name = line[:-len(",#genre#")].strip()
            if group_name:
                current_group = group_name
            else:
                _log_invalid(
                    "Empty TXT genre in %s at line %d",
                    source.url,
                    line_number,
                )
            continue

        item_order += 1

        if "," not in line:
            _log_invalid(
                "Invalid TXT record in %s at line %d",
                source.url,
                line_number,
            )
            continue

        channel_name, raw_url = line.split(",", 1)
        channel_name = channel_name.strip()
        raw_url = raw_url.strip()

        if not channel_name or not raw_url:
            _log_invalid(
                "Empty TXT channel name or URL in %s at line %d",
                source.url,
                line_number,
            )
            continue

        try:
            normalized_url = sources.normalize_source_url(raw_url)
        except (TypeError, ValueError) as exc:
            _log_invalid(
                "Invalid TXT stream URL in %s at line %d: %s",
                source.url,
                line_number,
                exc,
            )
            continue

        candidates.append(
            Candidate(
                url=normalized_url,
                name=channel_name,
                source_kind=source.kind,
                source_order=source.order,
                item_order=item_order,
                tvg_id=None,
                tvg_name=None,
                group_title=current_group or None,
                source_url=source.url,
            )
        )

    _check_budget(deadline)
    return tuple(candidates)


def _parse_subscription(
    result: DownloadResult,
    deadline: float,
) -> Tuple[Candidate, ...]:
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

    if not isinstance(result.content, bytes)
