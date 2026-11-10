
"""Bounded asynchronous source downloader.

This module downloads source content only.
It does not parse index files, parse subscriptions, or allocate candidates.

All HTTP/HTTPS requests are delegated to network.py so that IPv4,
public-address, TLS, redirect, and response-read policies stay centralized.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import List, Optional, Sequence, Tuple

import config
import network
from models import DownloadResult, SourceKind, SourceRecord


logger = logging.getLogger(__name__)


def _max_bytes_for_source(source: SourceRecord) -> int:
    """Return the configured download limit for this source kind."""
    if source.kind == SourceKind.AUTO_INDEX:
        return config.MAX_INDEX_BYTES

    if source.kind in (
        SourceKind.MANUAL_SUBSCRIPTION,
        SourceKind.AUTO_SUBSCRIPTION,
    ):
        return config.MAX_SUBSCRIPTION_BYTES

    raise ValueError(
        f"Source kind cannot be downloaded: {source.kind.value}"
    )


def _failed_result(
    source: SourceRecord,
    message: str,
    *,
    truncated: bool = False,
) -> DownloadResult:
    """Create a failed result using the shared model."""
    return DownloadResult(
        source=source,
        success=False,
        content=b"",
        status_code=None,
        error=message,
        bytes_received=0,
        truncated=truncated,
    )


async def _download_one(
    source: SourceRecord,
    semaphore: asyncio.Semaphore,
    deadline: float,
    started: List[bool],
    index: int,
) -> Optional[DownloadResult]:
    """Download one source within the shared collection deadline."""
    async with semaphore:
        loop = asyncio.get_running_loop()
        remaining = deadline - loop.time()

        if remaining <= 0:
            return None

        started[index] = True
        max_bytes = _max_bytes_for_source(source)
        timeout_seconds = min(
            config.SOURCE_DOWNLOAD_TIMEOUT_SECONDS,
            remaining,
        )

        try:
            result = await network.request(
                source.url,
                max_bytes,
                timeout_seconds=timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Unexpected download error for %s",
                source.url,
            )
            return _failed_result(
                source,
                f"Unexpected download error: {type(exc).__name__}",
            )

        status_code = result.status_code

        # A size-limit response or an interrupted response read is
        # incomplete even when no body bytes were received.
        # Other failed requests with partial bytes are also incomplete.
        truncated = (
            result.error == "Response exceeded read limit."
            or (
                result.error is not None
                and result.error.startswith(
                    "Response read interrupted:"
                )
            )
            or (
                not result.success
                and result.bytes_received > 0
            )
        )

        http_success = (
            status_code is not None
            and 200 <= status_code < 300
        )

        success = result.success and http_success

        error = result.error
        if result.success and not http_success:
            if status_code is None:
                error = "HTTP response status is missing."
            else:
                error = f"HTTP status is not successful: {status_code}"

        if success:
            error = None

        if not success:
            logger.warning(
                "Source download failed: %s (%s)",
                source.url,
                error or "unknown error",
            )

        return DownloadResult(
            source=source,
            success=success,
            content=result.content,
            status_code=status_code,
            error=error,
            bytes_received=result.bytes_received,
            truncated=truncated,
        )


async def collect_sources(
    sources: Sequence[SourceRecord],
    *,
    deadline: float,
) -> Tuple[DownloadResult, ...]:
    """Download the supplied sources concurrently and in bounded numbers.

    Args:
        sources:
            Sources already selected and ordered by main.py.
            AUTO_INDEX sources are limited by MAX_INDEX_BYTES.
            Manual and automatic subscription sources are limited by
            MAX_SUBSCRIPTION_BYTES.
        deadline:
            Absolute deadline from asyncio.get_running_loop().time().
            The caller should share one collection deadline between
            the first and second collection rounds. For the first index
            round, the caller should pass the earlier of the shared
            collection deadline and its 30-second index sub-deadline.

    Returns:
        Download results for requests that were actually started,
        preserving the original source order.

    Sources not started before the deadline are omitted. A started
    request cancelled by the collection deadline is returned as an
    incomplete failed result.
    """
    if not isinstance(sources, Sequence):
        raise TypeError("sources must be a sequence of SourceRecord")

    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
        raise TypeError("deadline must be an absolute monotonic timestamp")

    if not math.isfinite(deadline):
        raise ValueError("deadline must be finite")

    source_list = tuple(sources)

    for source in source_list:
        if not isinstance(source, SourceRecord):
            raise TypeError("Every item in sources must be a SourceRecord")
        _max_bytes_for_source(source)

    if not source_list:
        return ()

    max_running = config.MAX_CONCURRENT_DOWNLOADS
    max_waiting = config.DOWNLOAD_WAITING_QUEUE_LIMIT
    max_total = config.MAX_DOWNLOAD_TARGETS

    if max_running <= 0 or max_waiting < 0 or max_total <= 0:
        raise ValueError("Download concurrency and limits are invalid")

    if len(source_list) > max_total:
        raise ValueError(
            "The supplied source count exceeds MAX_DOWNLOAD_TARGETS"
        )

    if len(source_list) > max_running + max_waiting:
        raise ValueError(
            "The supplied source count exceeds the bounded "
            "concurrency and waiting-queue capacity"
        )

    loop = asyncio.get_running_loop()
    if deadline <= loop.time():
        return ()

    semaphore = asyncio.Semaphore(max_running)
    started = [False] * len(source_list)

    tasks = [
        asyncio.create_task(
            _download_one(
                source=source,
                semaphore=semaphore,
                deadline=deadline,
                started=started,
                index=index,
            )
        )
        for index, source in enumerate(source_list)
    ]

    try:
        remaining = max(0.0, deadline - loop.time())

        if remaining > 0:
            _, pending = await asyncio.wait(
                tasks,
                timeout=remaining,
                return_when=asyncio.ALL_COMPLETED,
            )
        else:
            pending = set(tasks)

        # The shared collection deadline has expired. Stop all unfinished
        # requests instead of allowing them to extend the collection stage.
        for task in pending:
            task.cancel()

        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    except asyncio.CancelledError:
        for task in tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    results: List[DownloadResult] = []

    # Read results in original source order, not completion order.
    for index, task in enumerate(tasks):
        if not started[index]:
            continue

        source = source_list[index]

        if task.cancelled():
            results.append(
                _failed_result(
                    source,
                    "Collection deadline reached; download cancelled.",
                    truncated=True,
                )
            )
            continue

        exception = task.exception()
        if exception is not None:
            logger.error(
                "Download task failed for %s: %s",
                source.url,
                type(exception).__name__,
            )
            results.append(
                _failed_result(
                    source,
                    f"Download task failed: {type(exception).__name__}",
                )
            )
            continue

        result = task.result()
        if result is not None:
            results.append(result)

    return tuple(results)
