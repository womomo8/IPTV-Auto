
"""Main orchestration for the IPTV automation pipeline.

This module coordinates the five business stages.
Business logic remains in the corresponding modules.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
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


def _log_summary(summary: RunSummary) -> None:
    """Print a concise and stable run summary."""
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
    sources_attempted: int = 0,
    candidates_collected: int = 0,
    candidates_validated: int = 0,
    candidates_passed: int = 0,
    candidates_incomplete: int = 0,
    channels_published: int = 0,
    incomplete: bool = False,
    messages: Sequence[str] = (),
) -> int:
    """Build the shared run summary and return the process exit code."""
    summary = RunSummary(
        mode=mode,
        exit_code=exit_code,
        stage_results=tuple(stage_results),
        sources_attempted=sources_attempted,
        candidates_collected=candidates_collected,
        candidates_validated=candidates_validated,
        candidates_passed=candidates_passed,
        candidates_incomplete=candidates_incomplete,
        channels_published=channels_published,
        incomplete=incomplete,
        messages=tuple(messages),
    )

    _log_summary(summary)
    return int(exit_code)


async def _collect_two_rounds(
    collection_start: float,
) -> tuple[tuple, int, bool]:
    """Execute index, manual-subscription, and automatic-subscription downloads.

    All download rounds share one collection deadline.
    The first index round additionally has its own 30-second sub-deadline.
    """
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

    # Manual subscriptions have first priority for the 30 source slots.
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

    # Round one: download automatic index files.
    # This call starts immediately so the 30-second sub-budget is real.
    if selected_indexes and loop.time() < index_deadline:
        index_results = await collector.collect_sources(
            selected_indexes,
            deadline=index_deadline,
        )
    else:
        index_results = ()

    # Download manual subscription sources under the shared 3-minute budget.
    if selected_manual and loop.time() < collection_deadline:
        manual_results = await collector.collect_sources(
            selected_manual,
            deadline=collection_deadline,
        )
    else:
        manual_results = ()

    # Parse downloaded index files. sources.py performs no network access.
    discovered_sources: list[SourceRecord] = []

    seen_urls = {
        item.url for item in manual_subscriptions
    }
    seen_urls.update(
        item.url for item in selected_indexes
    )

    next_auto_order = 0

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
    # Failed index downloads still consume their original source slots.
    automatic_slots = max(
        0,
        config.MAX_DOWNLOAD_TARGETS
        - len(manual_subscriptions)
        - len(index_results),
    )

    selected_automatic = tuple(
        discovered_sources[:automatic_slots]
    )

    if selected_automatic and loop.time() < collection_deadline:
        automatic_results = await collector.collect_sources(
            selected_automatic,
            deadline=collection_deadline,
        )
    else:
        automatic_results = ()

    download_results = (
        tuple(manual_results)
        + tuple(automatic_results)
    )

    all_results = (
        tuple(index_results)
        + tuple(manual_results)
        + tuple(automatic_results)
    )

    attempted = len(all_results)
    incomplete = any(
        result.truncated
        for result in all_results
    )

    logger.info(
        "采集完成：索引尝试=%d，人工订阅尝试=%d，自动订阅尝试=%d",
        len(index_results),
        len(manual_results),
        len(automatic_results),
    )

    logger.info(
        "采集来源总数=%d，自动发现来源=%d",
        attempted,
        len(discovered_sources),
    )

    return download_results, attempted, incomplete


async def run_pipeline(mode: RunMode) -> int:
    """Run the complete IPTV pipeline."""
    if not isinstance(mode, RunMode):
        logger.error("Invalid run mode.")
        return int(ExitCode.INPUT_ERROR)

    stage_results: list[StageResult] = []
    messages: list[str] = []

    sources_attempted = 0
    candidates_collected = 0
    candidates_validated = 0
    candidates_passed = 0
    candidates_incomplete = 0
    channels_published = 0
    run_incomplete = False

    current_stage = "启动"

    try:
        # --------------------------------------------------------
        # Stage 1: Collection
        # --------------------------------------------------------
        current_stage = "采集"
        stage_started = time.monotonic()
        collection_start = asyncio.get_running_loop().time()

        download_results, sources_attempted, collection_incomplete = (
            await _collect_two_rounds(collection_start)
        )

        run_incomplete = run_incomplete or collection_incomplete

        elapsed = time.monotonic() - stage_started

        stage_results.append(
            StageResult(
                stage_name=current_stage,
                elapsed_seconds=elapsed,
                success=True,
                incomplete=collection_incomplete,
            )
        )

        # --------------------------------------------------------
        # Stage 2: Normalization
        # --------------------------------------------------------
        current_stage = "整理"
        stage_started = time.monotonic()

        candidates = normalizer.normalize_candidates(
            download_results
        )

        elapsed = time.monotonic() - stage_started

        if elapsed > config.NORMALIZATION_BUDGET_SECONDS:
            raise TimeoutError(
                "Normalization stage exceeded its time budget."
            )

        candidates_collected = len(candidates)

        stage_results.append(
            StageResult(
                stage_name=current_stage,
                elapsed_seconds=elapsed,
                success=True,
            )
        )

        logger.info(
            "候选整理完成：保留 %d 条候选。",
            candidates_collected,
        )

        # --------------------------------------------------------
        # Stage 3: Validation
        # --------------------------------------------------------
        current_stage = "检测"
        stage_started = time.monotonic()

        validation_results = await validator.validate_candidates(
            candidates
        )

        elapsed = time.monotonic() - stage_started

        candidates_validated = len(validation_results)

        candidates_passed = sum(
            1
            for result in validation_results
            if result.completed and result.passed
        )

        candidates_incomplete = sum(
            1
            for result in validation_results
            if not result.completed
        )

        detection_incomplete = candidates_incomplete > 0
        run_incomplete = run_incomplete or detection_incomplete

        stage_results.append(
            Sta
