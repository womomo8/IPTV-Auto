
"""Tests for main pipeline orchestration and source scheduling."""

import unittest
from unittest.mock import AsyncMock, patch

import main
from models import (
    Candidate,
    DownloadResult,
    ExitCode,
    FilterResult,
    IndexParseResult,
    PublishResult,
    RunMode,
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


class TestValidationDiagnostics(unittest.TestCase):

    def make_candidate(self, item_order, url):
        return Candidate(
            url=url,
            name=f"频道{item_order}",
            source_kind=SourceKind.MANUAL_SUBSCRIPTION,
            source_order=1,
            item_order=item_order,
            source_url="https://example.com/manual.m3u",
        )

    def test_logs_source_totals_and_failure_reasons(self):
        candidate_passed = self.make_candidate(
            1, "https://example.com/1.ts"
        )
        candidate_failed = self.make_candidate(
            2, "https://example.com/2.ts"
        )
        candidate_incomplete = self.make_candidate(
            3, "https://example.com/3.ts"
        )

        results = (
            ValidationResult(
                candidate=candidate_passed,
                passed=True,
            ),
            ValidationResult(
                candidate=candidate_failed,
                passed=False,
                reason="HTTP 403",
            ),
            ValidationResult(
                candidate=candidate_incomplete,
                passed=False,
                completed=False,
                reason="连接超时",
            ),
        )

        with self.assertLogs("iptv.main", level="INFO") as captured:
            main._log_validation_diagnostics(results)

        output = "\n".join(captured.output)

        self.assertIn("总数：3", output)
        self.assertIn("通过：1", output)
        self.assertIn("失败：1", output)
        self.assertIn("未完成：1", output)
        self.assertIn("HTTP 403", output)
        self.assertIn("连接超时", output)

    def test_limits_failure_reasons_to_eight(self):
        results = tuple(
            ValidationResult(
                candidate=self.make_candidate(
                    index,
                    f"https://example.com/{index}.ts",
                ),
                passed=False,
                reason=f"错误原因{index}",
            )
            for index in range(1, 10)
        )

        with self.assertLogs("iptv.main", level="WARNING") as captured:
            main._log_validation_diagnostics(results)

        output = "\n".join(captured.output)

        self.assertIn("错误原因1", output)
        self.assertIn("错误原因8", output)
        self.assertNotIn("错误原因9", output)
        self.assertIn("其他失败原因", output)


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


class TestPipelineFailureHandling(
    unittest.IsolatedAsyncioTestCase
):

    async def test_stage_failure_stops_following_stages(self):
        with (
            patch.object(
                main,
                "_collect_two_rounds",
                new=AsyncMock(return_value=((), 0, False)),
            ),
            patch.object(
                main.normalizer,
                "normalize_candidates",
                return_value=(),
            ),
            patch.object(
                main.validator,
                "validate_candidates",
                new=AsyncMock(
                    side_effect=RuntimeError("validation stage failed")
                ),
            ) as validate_mock,
            patch.object(
                main.channel_filter,
                "filter_candidates",
            ) as filter_mock,
            patch.object(
                main.publisher,
                "publish",
            ) as publish_mock,
        ):
            result = await main.run_pipeline(RunMode.FORMAL)

        self.assertEqual(result, int(ExitCode.STAGE_ERROR))
        validate_mock.assert_awaited_once()
        filter_mock.assert_not_called()
        publish_mock.assert_not_called()

    async def test_publish_failure_exit_codes_are_propagated(self):
        for exit_code in (
            ExitCode.PUBLISH_ERROR,
            ExitCode.PUBLISH_UNCONFIRMED,
        ):
            with self.subTest(exit_code=exit_code):
                publish_result = PublishResult(
                    success=False,
                    exit_code=exit_code,
                    target_path="output/iptv.m3u",
                    error="publish test failure",
                )

                with (
                    patch.object(
                        main,
                        "_collect_two_rounds",
                        new=AsyncMock(
                            return_value=((), 0, False)
                        ),
                    ),
                    patch.object(
                        main.normalizer,
                        "normalize_candidates",
                        return_value=(),
                    ),
                    patch.object(
                        main.validator,
                        "validate_candidates",
                        new=AsyncMock(return_value=()),
                    ),
                    patch.object(
                        main.channel_filter,
                        "filter_candidates",
                        return_value=FilterResult(
                            m3u_content="#EXTM3U\n",
                            channel_count=0,
                        ),
                    ),
                    patch.object(
                        main.publisher,
                        "publish",
                        return_value=publish_result,
                    ) as publish_mock,
                ):
                    result = await main.run_pipeline(
                        RunMode.FORMAL
                    )

                self.assertEqual(result, int(exit_code))
                publish_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
