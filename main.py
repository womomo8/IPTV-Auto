
"""Main orchestration for the IPTV automation pipeline."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
import logging
import time
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
        discovered_sources[:automatic_slots]
    )

    if selected_automatic and loop.time() < collection_deadline:
        automatic_results = await collector.collect_sources(
            selected_automatic,
            deadline=collection_deadline,
        )
    else:
        automatic_results = ()

    not_started += max(
        0,
        len(selected_automatic) - len(automatic_results),
    )

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

    cancelled_or_truncated = any(
        result.truncated for result in all_results
    )

    incomplete = cancelled_or_truncated or not_started > 0

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

    if not_started > 0:
        logger.warning(
            "采集预算截断：%d 个已选来源未能启动下载。",
            not_started,
        )

    if cancelled_or_truncated:
        logger.warning(
            "采集存在已启动但被取消或读取超限的下载结果。"
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
        # Stage 1: Collection
        current_stage = "采集"
        stage_started = time.monotonic()
        collection_start = asyncio.get_running_loop().time()

        (
            download_results,
            sources_attempted,
            collection_incomplete,
        ) = await _collect_two_rounds(collection_start)

        run_incomplete = (
            run_incomplete or collection_incomplete
        )

        collection_message = None
        if collection_incomplete:
            collection_message = (
                "采集未完整完成：部分已选来源未能启动，"
                "或已启动下载被取消、读取超限。"
            )
            messages.append(collection_message)

        elapsed = time.monotonic() - stage_started
        stage_results.append(
            StageResult(
                stage_name=current_stage,
                elapsed_seconds=elapsed,
                success=True,
                incomplete=collection_incomplete,
                message=collection_message,
            )
        )

        # Stage 2: Normalization
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

        # Stage 3: Validation
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
        _log_validation_diagnostics(validation_results)
        detection_incomplete = candidates_incomplete > 0
        run_incomplete = (
            run_incomplete or detection_incomplete
        )

        stage_results.append(
            StageResult(
                stage_name=current_stage,
                elapsed_seconds=elapsed,
                success=True,
                incomplete=detection_incomplete,
                message=(
                    f"有 {candidates_incomplete} 条候选未完成验证。"
                    if detection_incomplete
                    else None
                ),
            )
        )

        # Stage 4: Filtering
        current_stage = "筛选"
        stage_started = time.monotonic()

        filter_result = channel_filter.filter_candidates(
            validation_results
        )

        elapsed = time.monotonic() - stage_started
        stage_results.append(
            StageResult(
                stage_name=current_stage,
                elapsed_seconds=elapsed,
                success=True,
            )
        )

        logger.info(
            "筛选完成：最终有效频道 %d 条。",
            filter_result.channel_count,
        )

        # Stage 5: Publication
        current_stage = "发布"
        stage_started = time.monotonic()

        publish_result = publisher.publish(
            filter_result,
            mode,
            repository_root=Path(__file__).resolve().parent,
        )

        elapsed = time.monotonic() - stage_started
        stage_results.append(
            StageResult(
                stage_name=current_stage,
                elapsed_seconds=elapsed,
                success=publish_result.success,
                message=publish_result.error,
            )
        )

        if publish_result.success:
            channels_published = filter_result.channel_count
        else:
            messages.append(
                publish_result.error or "Publication failed."
            )

        # Stage 6: Summary and cleanup.
        current_stage = "收尾"
        cleanup_started = time.monotonic()
        stage_results.append(
            StageResult(
                stage_name=current_stage,
                elapsed_seconds=0.0,
                success=True,
                incomplete=run_incomplete,
            )
        )

        return _finish(
            mode,
            publish_result.exit_code,
            stage_results,
            cleanup_started=cleanup_started,
            sources_attempted=sources_attempted,
            candidates_collected=candidates_collected,
            candidates_validated=candidates_validated,
            candidates_passed=candidates_passed,
            candidates_incomplete=candidates_incomplete,
            channels_published=channels_published,
            incomplete=run_incomplete,
            messages=messages,
        )

    except Exception as exc:
        elapsed = 0.0
        if "stage_started" in locals():
            elapsed = max(
                0.0,
                time.monotonic() - stage_started,
            )

        logger.exception(
            "%s 阶段发生不可恢复错误。",
            current_stage,
        )

        stage_results.append(
            StageResult(
                stage_name=current_stage,
                elapsed_seconds=elapsed,
                success=False,
                message=f"{type(exc).__name__}: {exc}",
            )
        )

        messages.append(
            f"{current_stage}阶段失败："
            f"{type(exc).__name__}: {exc}"
        )

        cleanup_started = time.monotonic()

        return _finish(
            mode,
            ExitCode.STAGE_ERROR,
            stage_results,
            cleanup_started=cleanup_started,
            sources_attempted=sources_attempted,
            candidates_collected=candidates_collected,
            candidates_validated=candidates_validated,
            candidates_passed=candidates_passed,
            candidates_incomplete=candidates_incomplete,
            channels_published=channels_published,
            incomplete=run_incomplete,
            messages=messages,
        )


def main() -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="China IPTV automatic subscription pipeline."
    )
    parser.add_argument(
        "--mode",
        choices=("formal", "test"),
        default="formal",
        help=(
            "formal: generate and publish the official subscription; "
            "test: write only the isolated test output."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    mode = RunMode(args.mode)

    try:
        return asyncio.run(run_pipeline(mode))
    except KeyboardInterrupt:
        logger.warning("运行被手动中断。")
        return int(ExitCode.STAGE_ERROR)


if __name__ == "__main__":
    raise SystemExit(main())
