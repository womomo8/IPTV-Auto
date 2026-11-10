
"""Business tests for bounded source collection."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import collector
import config
from models import NetworkResult, SourceKind, SourceRecord


def make_source(url, kind=SourceKind.AUTO_SUBSCRIPTION, order=1):
    return SourceRecord(url=url, kind=kind, order=order)


class TestDownloadLimits(unittest.IsolatedAsyncioTestCase):

    async def test_uses_index_and_subscription_size_limits(self):
        index = make_source(
            "https://example.com/index.txt",
            SourceKind.AUTO_INDEX,
        )
        subscription = make_source(
            "https://example.com/live.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
            2,
        )

        async def fake_request(url, max_bytes, *, timeout_seconds):
            return NetworkResult(
                success=True,
                requested_url=url,
                status_code=200,
                content=b"data",
                bytes_received=4,
            )

        with patch.object(
            collector.network,
            "request",
            new=AsyncMock(side_effect=fake_request),
        ) as request:
            results = await collector.collect_sources(
                (index, subscription),
                deadline=asyncio.get_running_loop().time() + 2,
            )

        self.assertEqual(len(results), 2)

        limits = {
            call.args[0]: call.args[1]
            for call in request.call_args_list
        }

        self.assertEqual(
            limits[index.url],
            config.MAX_INDEX_BYTES,
        )
        self.assertEqual(
            limits[subscription.url],
            config.MAX_SUBSCRIPTION_BYTES,
        )

    async def test_rejects_manual_single_stream_as_download_source(self):
        source = make_source(
            "https://example.com/live.ts",
            SourceKind.MANUAL_STREAM,
        )

        with self.assertRaises(ValueError):
            await collector.collect_sources(
                (source,),
                deadline=asyncio.get_running_loop().time() + 2,
            )


class TestCollectionResults(unittest.IsolatedAsyncioTestCase):

    async def test_successful_download_returns_complete_result(self):
        source = make_source("https://example.com/live.m3u")

        async def fake_request(url, max_bytes, *, timeout_seconds):
            return NetworkResult(
                success=True,
                requested_url=url,
                final_url=url,
                status_code=200,
                content=b"playlist",
                bytes_received=8,
            )

        with patch.object(
            collector.network,
            "request",
            new=AsyncMock(side_effect=fake_request),
        ):
            results = await collector.collect_sources(
                (source,),
                deadline=asyncio.get_running_loop().time() + 2,
            )

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].success)
        self.assertFalse(results[0].truncated)
        self.assertEqual(results[0].content, b"playlist")
        self.assertEqual(results[0].bytes_received, 8)
        self.assertEqual(results[0].status_code, 200)
        self.assertIsNone(results[0].error)

    async def test_preserves_source_order_not_completion_order(self):
        first = make_source(
            "https://example.com/first.m3u",
            order=1,
        )
        second = make_source(
            "https://example.com/second.m3u",
            order=2,
        )

        async def fake_request(url, max_bytes, *, timeout_seconds):
            if url == first.url:
                await asyncio.sleep(0.04)
            else:
                await asyncio.sleep(0.001)

            return NetworkResult(
                success=True,
                requested_url=url,
                status_code=200,
                content=url.encode("utf-8"),
                bytes_received=len(url),
            )

        with patch.object(
            collector.network,
            "request",
            new=AsyncMock(side_effect=fake_request),
        ):
            results = await collector.collect_sources(
                (first, second),
                deadline=asyncio.get_running_loop().time() + 2,
            )

        self.assertEqual(
            tuple(item.source.url for item in results),
            (first.url, second.url),
        )

    async def test_non_success_http_status_is_download_failure(self):
        source = make_source("https://example.com/not-found.m3u")

        async def fake_request(url, max_bytes, *, timeout_seconds):
            return NetworkResult(
                success=True,
                requested_url=url,
                status_code=404,
                content=b"not found",
                bytes_received=9,
            )

        with patch.object(
            collector.network,
            "request",
            new=AsyncMock(side_effect=fake_request),
        ):
            results = await collector.collect_sources(
                (source,),
                deadline=asyncio.get_running_loop().time() + 2,
            )

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].success)
        self.assertTrue(results[0].truncated)
        self.assertEqual(results[0].status_code, 404)
        self.assertIn("404", results[0].error)

    async def test_missing_http_status_is_download_failure(self):
        source = make_source("https://example.com/missing-status.m3u")

        async def fake_request(url, max_bytes, *, timeout_seconds):
            return NetworkResult(
                success=True,
                requested_url=url,
                status_code=None,
                content=b"data",
                bytes_received=4,
            )

        with patch.object(
            collector.network,
            "request",
            new=AsyncMock(side_effect=fake_request),
        ):
            results = await collector.collect_sources(
                (source,),
                deadline=asyncio.get_running_loop().time() + 2,
            )

        self.assertFalse(results[0].success)
        self.assertTrue(results[0].truncated)
        self.assertIn("status is missing", results[0].error)

    async def test_failed_partial_download_is_marked_truncated(self):
        source = make_source("https://example.com/interrupted.m3u")

        async def fake_request(url, max_bytes, *, timeout_seconds):
            return NetworkResult(
                success=False,
                requested_url=url,
                status_code=200,
                content=b"partial",
                bytes_received=7,
                error="Connection interrupted",
            )

        with patch.object(
            collector.network,
            "request",
            new=AsyncMock(side_effect=fake_request),
        ):
            results = await collector.collect_sources(
                (source,),
                deadline=asyncio.get_running_loop().time() + 2,
            )

        self.assertFalse(results[0].success)
        self.assertTrue(results[0].truncated)
        self.assertEqual(results[0].content, b"partial")
        self.assertEqual(results[0].bytes_received, 7)

    async def test_response_read_limit_is_marked_truncated(self):
        source = make_source("https://example.com/large.m3u")

        async def fake_request(url, max_bytes, *, timeout_seconds):
            return NetworkResult(
                success=False,
                requested_url=url,
                status_code=200,
                content=b"partial",
                bytes_received=7,
                error="Response exceeded read limit.",
            )

        with patch.object(
            collector.network,
            "request",
            new=AsyncMock(side_effect=fake_request),
        ):
            results = await collector.collect_sources(
                (source,),
                deadline=asyncio.get_running_loop().time() + 2,
            )

        self.assertFalse(results[0].success)
        self.assertTrue(results[0].truncated)


class TestCollectionDeadlinesAndLimits(
    unittest.IsolatedAsyncioTestCase
):

    async def test_expired_deadline_starts_no_download(self):
        source = make_source("https://example.com/live.m3u")

        request = AsyncMock()

        with patch.object(
            collector.network,
            "request",
            new=request,
        ):
            results = await collector.collect_sources(
                (source,),
                deadline=asyncio.get_running_loop().time() - 1,
            )

        self.assertEqual(results, ())
        request.assert_not_awaited()

    async def test_deadline_cancels_started_download_as_truncated(self):
        source = make_source("https://example.com/slow.m3u")
        started = asyncio.Event()

        async def fake_request(url, max_bytes, *, timeout_seconds):
            started.set()
            await asyncio.Event().wait()

        with patch.object(
            collector.network,
            "request",
            new=AsyncMock(side_effect=fake_request),
        ):
            results = await collector.collect_sources(
                (source,),
                deadline=asyncio.get_running_loop().time() + 0.05,
            )

        self.assertTrue(started.is_set())
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].success)
        self.assertTrue(results[0].truncated)
        self.assertIn("deadline", results[0].error.lower())

    async def test_rejects_source_count_over_total_limit(self):
        sources = tuple(
            make_source(
                f"https://example.com/{index}.m3u",
                order=index,
            )
            for index in range(3)
        )

        with patch.object(
            collector.config,
            "MAX_DOWNLOAD_TARGETS",
            2,
        ):
            with self.assertRaises(Val
