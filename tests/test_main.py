
"""Tests for main pipeline orchestration and source scheduling."""

import unittest
from unittest.mock import AsyncMock, patch

import main
from models import (
    Candidate,
    DownloadResult,
    IndexParseResult,
    SourceKind,
    SourceRecord,
    ValidationResult,
)


def make_source(url, kind, order):
    return SourceRecord(
        url=url,
        kind=kind,
        order=order,
    )


def make_download(source):
    return DownloadResult(
        source=source,
        success=True,
        content=b"#EXTM3U\n",
        status_code=200,
        bytes_received=8,
    )


def make_candidate(
    url,
    source_url,
    kind=SourceKind.MANUAL_SUBSCRIPTION,
    item_order=1,
):
    return Candidate(
        url=url,
        name=f"频道{item_order}",
        source_kind=kind,
        source_order=1,
        item_order=item_order,
        source_url=source_url,
    )


class TestValidationDiagnostics(unittest.TestCase):

    def test_logs_source_counts_and_separates_failure_from_incomplete(self):
        source_a = "https://example.com/manual.txt"
        source_b = "https://example.com/auto.m3u"

        results = (
            ValidationResult(
                candidate=make_candidate(
                    "http://203.0.113.1/live1",
                    source_a,
                    item_order=1,
                ),
                passed=False,
                reason="MPEG-TS sync check failed.",
            ),
            ValidationResult(
                candidate=make_candidate(
                    "http://203.0.113.1/live2",
                    source_a,
                    item_order=2,
                ),
                passed=False,
                reason="MPEG-TS sync check failed.",
            ),
            ValidationResult(
                candidate=make_candidate(
                    "http://203.0.113.1/live3",
                    source_a,
                    item_order=3,
                ),
                passed=False,
                completed=False,
                reason="Candidate validation budget exhausted.",
            ),
            ValidationResult(
                candidate=make_candidate(
                    "http://203.0.113.2/live1",
                    source_b,
                    kind=SourceKind.AUTO_SUBSCRIPTION,
                ),
                passed=True,
            ),
        )

        with self.assertLogs(
            "iptv.main",
            level="INFO",
        ) as captured:
            main._log_validation_diagnostics(results)

        output = "\n".join(captured.output)

        self.assertIn(
            "检测来源统计：人工订阅 | "
            f"{source_a} | 候选=3 | 通过=0 | 失败=2 | 未完成=1",
            output,
        )

        self.assertIn(
            "检测失败原因：MPEG-TS sync check failed. | 2条",
            output,
        )

        self.assertIn(
            "检测未完成原因：Candidate validation budget exhausted. | 1条",
            output,
        )

        self.assertIn(
            "检测来源统计：自动订阅 | "
            f"{source_b} | 候选=1 | 通过=1 | 失败=0 | 未完成=0",
            output,
        )

    def test_manual_streams_are_logged_separately(self):
        results = (
            ValidationResult(
                candidate=make_candidate(
                    "http://203.0.113.1/live1",
                    None,
                    kind=SourceKind.MANUAL_STREAM,
                    item_order=1,
                ),
                passed=False,
                reason="Connection failed.",
            ),
            ValidationResult(
                candidate=make_candidate(
                    "http://203.0.113.2/live2",
                    None,
                    kind=SourceKind.MANUAL_STREAM,
                    item_order=2,
                ),
                passed=False,
                reason="Connection failed.",
            ),
        )

        with self.assertLogs(
            "iptv.main",
            level="INFO",
        ) as captured:
            main._log_validation_diagnostics(results)

        output = "\n".join(captured.output)

        self.assertIn(
            "人工单条地址：http://203.0.113.1/live1",
            output,
        )
        self.assertIn(
            "人工单条地址：http://203.0.113.2/live2",
            output,
        )

    def test_reason_output_is_limited_to_eight_types(self):
        source_url = "https://example.com/manual.txt"

        results = tuple(
            ValidationResult(
                candidate=make_candidate(
                    f"http://203.0.113.1/live{index}",
                    source_url,
                    item_order=index,
                ),
                passed=False,
                reason=f"Failure reason {index}",
            )
            for index in range(10)
        )

        with self.assertLogs(
            "iptv.main",
            level="WARNING",
        ) as captured:
            main._log_validation_diagnostics(results)

        output = "\n".join(captured.output)

        self.assertIn(
            "检测失败原因：其余 2 种原因，共 2 条",
            output,
        )


class TestCollectionScheduling(unittest.IsolatedAsyncioTestCase):

    async def test_automatic_quota_uses_actual_started_index_downloads(self):
        manual_stream = make_source(
            "https://example.com/manual.ts",
            SourceKind.MANUAL_STREAM,
            1,
        )
        manual_subscription = make_source(
            "https://example.com/manual.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
            2,
        )
        index_one = make_source(
            "https://example.com/index-one.txt",
            SourceKind.AUTO_INDEX,
            3,
        )
        index_two = make_source(
            "https://example.com/index-two.txt",
            SourceKind.AUTO_INDEX,
            4,
        )

        discovered = (
            make_source(
                manual_subscription.url,
                SourceKind.AUTO_SUBSCRIPTION,
                1,
            ),
            make_source(
                index_one.url,
                SourceKind.AUTO_SUBSCRIPTION,
                2,
            ),
            make_source(
                "https://example.com/auto-one.m3u",
                SourceKind.AUTO_SUBSCRIPTION,
                3,
            ),
            make_source(
                "https://example.com/auto-two.m3u",
                SourceKind.AUTO_SUBSCRIPTION,
                4,
            ),
            make_source(
                "https://example.com/auto-three.m3u",
                SourceKind.AUTO_SUBSCRIPTION,
                5,
            ),
            make_source(
                "https://example.com/auto-four.m3u",
                SourceKind.AUTO_SUBSCRIPTION,
                6,
            ),
        )

        index_result = make_download(index_one)
        manual_result = make_download(manual_subscription)

        async_calls = []

        async def fake_collect(selected, *, deadline):
            selected = tuple(selected)
            async_calls.append((selected, deadline))

            if len(async_calls) == 1:
                # Two indexes were selected, but only one actually
                # started and returned a result.
                return (index_result,)

            if len(async_calls) == 2:
                return (manual_result,)

            return tuple(
                make_download(source)
                for source in selected
            )

        with (
            patch.object(
                main.sources,
                "build_source_list",
                return_value=(
                    manual_stream,
                    manual_subscription,
                    index_one,
                    index_two,
                ),
            ),
            patch.object(
                main.sources,
                "parse_index_download",
                return_value=IndexParseResult(
                    index_source=index_one,
                    sources=discovered,
                ),
            ),
            patch.object(
                main.sources,
                "normalize_source_url",
                side_effect=lambda url: url,
            ),
            patch.object(
                main.collector,
                "collect_sources",
                new=AsyncMock(side_effect=fake_collect),
            ),
            patch.object(
                main.config,
                "MAX_DOWNLOAD_TARGETS",
                5,
            ),
            patch.object(
                main.config,
                "MAX_AUTO_INDEX_DOWNLOADS",
                2,
            ),
        ):
            loop = __import__("asyncio").get_running_loop()

            results, attempted, incomplete = (
                await main._collect_two_rounds(loop.time() + 60)
            )

        # First round: two indexes selected in configured order.
        self.assertEqual(
            tuple(item.url for item in async_calls[0][0]),
            (index_one.url, index_two.url),
        )

        # Second call: manual subscription retains priority.
        self.assertEqual(
            tuple(item.url for item in async_calls[1][0]),
            (manual_subscription.url,),
        )

        # Only one index actually returned a result.
        # Therefore automatic quota is 5 - 1 - 1 = 3.
        # Duplicate manual and index URLs must be excluded.
        self.assertEqual(
            tuple(item.url for item in async_calls[2][0]),
            (
                "https://example.com/auto-one.m3u",
                "https://example.com/auto-two.m3u",
                "https://example.com/auto-three.m3u",
            ),
        )

        # Index downloads are not passed to normalization.
        self.assertEqual(
            tuple(item.source.url for item in results),
            (
                manual_subscription.url,
                "https://example.com/auto-one.m3u",
                "https://example.com/auto-two.m3u",
                "https://example.com/auto-three.m3u",
            ),
        )

        self.assertEqual(attempted, 5)
        self.assertTrue(incomplete)

    async def test_manual_stream_does_not_consume_download_quota(self):
        manual_stream = make_source(
            "https://example.com/live.ts",
            SourceKind.MANUAL_STREAM,
            1,
        )
        manual_subscription = make_source(
            "https://example.com/manual.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
            2,
        )
        index = make_source(
            "https://example.com/index.txt",
            SourceKind.AUTO_INDEX,
            3,
        )

        calls = []

        async def fake_collect(selected, *, deadline):
            selected = tuple(selected)
            calls.append(selected)

            if selected == (index,):
                return ()

            return (make_download(manual_subscription),)

        with (
            patch.object(
                main.sources,
                "build_source_list",
                return_value=(
                    manual_stream,
                    manual_subscription,
                    index,
                ),
            ),
            patch.object(
                main.collector,
                "collect_sources",
                new=AsyncMock(side_effect=fake_collect),
            ),
            patch.object(
                main.config,
                "MAX_DOWNLOAD_TARGETS",
                2,
            ),
            patch.object(
                main.config,
                "MAX_AUTO_INDEX_DOWNLOADS",
                1,
            ),
        ):
            loop = __import__("asyncio").get_running_loop()

            results, attempted, incomplete = (
                await main._collect_two_rounds(loop.time() + 60)
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], (index,))
        self.assertEqual(calls[1], (manual_subscription,))
        self.assertEqual(len(results), 1)
        self.assertEqual(attempted, 1)
        self.assertTrue(incomplete)


class TestPipelineInput(unittest.TestCase):

    def test_invalid_run_mode_returns_input_error(self):
        result = __import__("asyncio").run(
            main.run_pipeline("invalid")
        )

        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
