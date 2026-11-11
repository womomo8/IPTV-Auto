
"""Main orchestration for the IPTV automation pipeline."""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Sequence

import collector
import config
import filter as channel_filter
import normalizer
import publisher
import sources
import validator
from models import (
    ExitCode,
    RunMode,
    RunSummary,
    SourceKind,
    SourceRecord,
    StageResult,
)


logger = logging.getLogger("iptv.main")


_SOURCE_KIND_LABELS = {
    SourceKind.MANUAL_STREAM: "人工单条地址",
    SourceKind.MANUAL_SUBSCRIPTION: "人工订阅",
    SourceKind.AUTO_SUBSCRIPTION: "自动订阅",
}


def _clean_validation_reason(reason: str | None) -> str:
    """Normalize and limit a validation reason for readable logs."""
    cleaned = " ".join((reason or "未提供原因").split())

    if len(cleaned) > 200:
        return cleaned[:197] + "..."

    return cleaned


def _log_reason_counts(
    label: str,
    reasons: Counter[str],
) -> None:
    """Log grouped reasons without producing excessive output."""
    items = reasons.most_common()

    for reason, count in items[:8]:
        logger.warning(
            "%s：%s | %d条",
            label,
            reason,
            count,
        )

    if len(items) > 8:
        omitted_count = sum(
            count
            for _, count in items[8:]
        )
        omitted_types = len(items) - 8

        logger.warning(
            "%s：其余 %d 种原因，共 %d 条",
            label,
            omitted_types,
            omitted_count,
        )


def _log_validation_diagnostics(
    validation_results: Sequence,
) -> None:
    """Log validation counts and reasons grouped by source."""
    grouped: dict[tuple[str, str], list] = {}

    for result in validation_results:
        candidate = result.candidate
        source_kind = candidate.source_kind

        kind_label = _SOURCE_KIND_LABELS.get(
            source_kind,
            source_kind.value,
        )

        if source_kind == SourceKind.MANUAL_STREAM:
            source_label = (
                f"人工单条地址：{candidate.url}"
            )
        else:
            source_label = (
                candidate.source_url or "来源地址缺失"
            )

        key = (kind_label, source_label)
        grouped.setdefault(key, []).append(result)

    for (kind_label, source_label), results in grouped.items():
        passed = sum(
            1
            for result in results
            if result.completed and result.passed
        )

        failed = sum(
            1
            for result in results
            if result.completed and not result.passed
        )

        incomplete = sum(
            1
            for result in results
            if not result.completed
        )

        logger.info(
            "检测来源统计：%s | %s | 候选=%d | 通过=%d | 失败=%d | 未完成=%d",
            kind_label,
            source_label,
            len(results),
            passed,
            failed,
            incomplete,
        )

        failure_reasons = Counter(
            _clean_validation_reason(result.reason)
            for result in results
            if result.completed and not result.passed
        )

        incomplete_reasons = Counter(
            _clean_validation_reason(result.reason)
            for result in results
            if not result.completed
        )

        _log_reason_counts(
            "检测失败原因",
            failure_reasons,
        )

        _log_reason_counts(
            "检测未完成原因",
            incomplete_reasons,
        )


def _log_summary(summary: RunSummary) -> None:
    """Print a concise run summary."""
    logger.info("========== IPTV RUN SUMMARY ==========")
    logger.info("运行模式：%s", summary.mode.value)
    logger.info("退出码：%s", int(summary.exit_code))
    logger.info("尝试下载来源：%d", summary.sources_attempted)
    logger.info("整理后候选：%d", summary.candidates_collected)
    logger.info("已验证候选：%d", summary.candidates_validated)
    logger.info("验证通过候选：%d", summary.candidates_passed)
    logger.info("未完成候选：%d", summary.candidates_incomplete)
    logger.info("发布频道：%d", summary.channels_published)
    logger.info("运行是否不完整：%s", summary.incomplete)

    for stage in summary.stage_results:
        logger.info(
            "阶段：%s | 耗时：%.2fs | 成功：%s | 不完整：%s",
            stage.stage_name,
            stage.elapsed_seconds,
            stage.success,
            stage.incomplete,
        )
        if stage.message:
            logger.info("阶段说明：%s", stage.message)

    for message in summary.messages:
        logger.warning("运行说明：%s", message)

    logger.info("======================================")


def _finish(
    mode: RunMode,
    exit_code: ExitCode,
    stage_results: Sequence[StageResult],
    *,
    cleanup_started: float | None = None,
    sources_attempted: int = 0,
    candidates_collected: int = 0,
    candidates_validated: int = 0,
    candidates_passed: int = 0,
    candidates_incomplete: int = 0,
    channels_published: int = 0,
    incomplete: bool = False,
    messages: Sequence[str] = (),
) -> int:
    """Build the shared run summary and record cleanup duration."""
    final_stages = list(stage_results)

    if cleanup_started is not None:
        if final_stages and final_stages[-1].stage_name == "收尾":
            final_stages[-1] = replace(
                final_stages[-1],
                elapsed_seconds=0.0,
            )
        else:
            final_stages.append(
                StageResult(
                    stage_name="收尾",
                    elapsed_seconds=0.0,
                    success=True,
                    incomplete=incomplete,
                )
            )

    summary = RunSummary(
        mode=mode,
        exit_code=exit_code,
        stage_results=tuple(final_stages),
        sources_attempted=sources_attempted,
        candidates_collected=candidates_collected,
        candidates_validated=candidates_validated,
        candidates_passed=candidates_passed,
        candidates_incomplete=candidates_incomplete,
        channels_published=channels_published,
        incomplete=incomplete,
        messages=tuple(messages),
    )

    if cleanup_started is not None:
        cleanup_elapsed = max(
            0.0,
            time.monotonic() - cleanup_started,
        )
        final_stages[-1] = replace(
            final_stages[-1],
            elapsed_seconds=cleanup_elapsed,
        )
        summary = replace(
            summary,
            stage_results=tuple(final_stages),
        )

    _log_summary(summary)
    return int(exit_code)


async def _collect_two_rounds(
    collection_start: float,
) -> tuple[tuple, int, bool]:
    """Run index and subscription downloads under shared deadlines."""
    loop = asyncio.get_running_loop()

    collection_deadline = (
        collection_start + config.COLLECTION_BUDGET_SECONDS
    )
    index_deadline = min(
        collection_deadline,
        collection_start + config.INDEX_DOWNLOAD_BUDGET_SECONDS,
    )

    all_sources = sources.build_source_list(
        auto_index_urls=config.AUTO_INDEX_URLS,
    )

    manual_streams = tuple(
        item
        for item in all_sources
        if item.kind == SourceKind.MANUAL_STREAM
    )
    manual_subscriptions = tuple(
        item
        for item in all_sources
        if item.kind == SourceKind.MANUAL_SUBSCRIPTION
    )
    automatic_indexes = tuple(
        item
        for item in all_sources
        if item.kind == SourceKind.AUTO_INDEX
    )

    selected_manual = manual_subscriptions[
        :config.MAX_DOWNLOAD_TARGETS
    ]

    remaining_slots = max(
        0,
        config.MAX_DOWNLOAD_TARGETS - len(manual_subscriptions),
    )

    selected_indexes = automatic_indexes[
        :min(config.MAX_AUTO_INDEX_DOWNLOADS, remaining_slots)
    ]

    not_started = 0

    # Round one: automatic index downloads.
    if selected_indexes and loop.time() < index_deadline:
        index_results = await collector.collect_sources(
            selected_indexes,
            deadline=index_deadline,
        )
    else:
        index_results = ()

    not_started += max(
        0,
        len(selected_indexes) - len(index_results),
    )

    # Download manual subscription sources.
    if selected_manual and loop.time() < collection_deadline:
        manual_results = await collector.collect_sources(
            selected_manual,
            deadline=collection_deadline,
        )
    else:
        manual_results = ()

    not_started += max(
        0,
        len(selected_manual) - len(manual_results),
    )

    # Manual streams, manual subscriptions, and selected index URLs
    # have higher priority than discovered automatic subscriptions.
    seen_urls = {
        item.url
        for item in manual_streams + manual_subscriptions
    }
    seen_urls.update(item.url for item in selected_indexes)

    discovered_sources: list[SourceRecord] = []
    next_auto_order = 0

    # sources.py only parses downloaded index content; it does no I/O.
    for download_result in index_results:
        parsed = sources.parse_index_download(download_result)

        for discovered in parsed.sources:
            normalized_url = sources.normalize_source_url(
                discovered.url
            )

            if normalized_url in seen_urls:
                continue

            seen_urls.add(normalized_url)
            next_auto_order += 1

            discovered_sources.append(
                SourceRecord(
                    url=normalized_url,
                    kind=SourceKind.AUTO_SUBSCRIPTION,
                    order=next_auto_order,
                )
            )

    # Round two: automatic subscription downloads.
    # Only index downloads actually started consume source slots.
    automatic_slots = max(
        0,
        config.MAX_DOWNLOAD_TARGETS
        - len(manual_subscriptions)
        - len(index_results),
    )

    selected_automatic = tuple(
   
