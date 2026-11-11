"""Business tests for IPTV candidate validation."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import validator
from models import (
    Candidate,
    NetworkResult,
    SourceKind,
    StreamType,
    ValidationResult,
)


def make_candidate(url="https://example.com/live.ts", order=0):
    return Candidate(
        url=url,
        name=f"频道{order}",
        source_kind=SourceKind.MANUAL_STREAM,
        source_order=order,
        item_order=order,
    )


def make_network_result(
    content=b"",
    *,
    url="https://example.com/live.ts",
    success=True,
    status_code=200,
    content_type=None,
    error=None,
):
    return NetworkResult(
        success=success,
        requested_url=url,
        content=content,
        final_url=url,
        remote_ip="8.8.8.8",
        status_code=status_code,
        content_type=content_type,
        bytes_received=len(content),
        error=error,
    )


def make_ts_data():
    data = bytearray(4 * 188 + 1)
    for offset in (0, 188, 376, 564, 752):
        data[offset] = 0x47
    return bytes(data)


class TestTSHelpers(unittest.TestCase):

    def test_accepts_valid_ts_sync(self):
        self.assertTrue(validator._has_ts_sync(make_ts_data()))

    def test_rejects_missing_ts_sync(self):
        self.assertFalse(validator._has_ts_sync(bytes(941)))

    def test_rejects_non_bytes_data(self):
        self.assertFalse(validator._has_ts_sync("not bytes"))

    def test_accepts_sync_at_nonzero_offset(self):
        data = bytearray(947)
        for offset in (7, 195, 383, 571, 759):
            data[offset] = 0x47
        self.assertTrue(validator._has_ts_sync(bytes(data)))


class TestHLSHelpers(unittest.TestCase):

    def test_detects_hls_url_case_insensitively(self):
        self.assertTrue(
            validator._is_hls_url("https://example.com/LIVE.M3U8")
        )

    def test_rejects_ts_url_as_hls(self):
        self.assertFalse(
            validator._is_hls_url("https://example.com/live.ts")
        )

    def test_detects_hls_playlist_header(self):
        result = make_network_result(b"\xef\xbb\xbf #EXTM3U\n")
        self.assertTrue(validator._is_hls_content(result))

    def test_detects_hls_content_type(self):
        result = make_network_result(
            b"playlist",
            content_type="application/vnd.apple.mpegurl",
        )
        self.assertTrue(validator._is_hls_content(result))

    def test_rejects_non_hls_content(self):
        result = make_network_result(
            b"transport stream",
            content_type="video/mp2t",
        )
        self.assertFalse(validator._is_hls_content(result))

    def test_playlist_text_accepts_utf8_bom(self):
        result = make_network_result(
            b"\xef\xbb\xbf#EXTM3U\n#EXTINF:5,\nsegment.ts\n"
        )
        self.assertIsNotNone(validator._playlist_text(result))

    def test_playlist_text_rejects_wrong_header(self):
        result = make_network_result(b"NOT-M3U\nsegment.ts\n")
        self.assertIsNone(validator._playlist_text(result))

    def test_playlist_text_rejects_invalid_utf8(self):
        result = make_network_result(b"#EXTM3U\n\xff")
        self.assertIsNone(validator._playlist_text(result))

    def test_playlist_text_rejects_failed_request(self):
        result = make_network_result(
            b"#EXTM3U\n",
            success=False,
            status_code=500,
        )
        self.assertIsNone(validator._playlist_text(result))

    def test_parses_quoted_attributes(self):
        attributes = validator._parse_attributes(
            'BANDWIDTH=1200000,RESOLUTION="1280x720"'
        )
        self.assertEqual(attributes["BANDWIDTH"], "1200000")
        self.assertEqual(attributes["RESOLUTION"], "1280x720")

    def test_rejects_encrypted_key(self):
        error = validator._check_unsupported_tags([
            '#EXT-X-KEY:METHOD=AES-128,URI="key.bin"'
        ])
        self.assertIsNotNone(error)

    def test_allows_key_method_none(self):
        error = validator._check_unsupported_tags([
            "#EXT-X-KEY:METHOD=NONE"
        ])
        self.assertIsNone(error)

    def test_rejects_session_key(self):
        error = validator._check_unsupported_tags([
            '#EXT-X-SESSION-KEY:METHOD=AES-128,URI="key.bin"'
        ])
        self.assertIsNotNone(error)

    def test_rejects_fmp4_map(self):
        error = validator._check_unsupported_tags([
            '#EXT-X-MAP:URI="init.mp4"'
        ])
        self.assertIsNotNone(error)

    def test_sorts_master_variants_by_bandwidth(self):
        lines = [
            "#EXTM3U",
            "#EXT-X-STREAM-INF:BANDWIDTH=100",
            "low.m3u8",
            "#EXT-X-STREAM-INF:BANDWIDTH=300",
            "high.m3u8",
            "#EXT-X-STREAM-INF:BANDWIDTH=200",
            "middle.m3u8",
        ]
        variants = validator._parse_master_variants(lines)
        self.assertEqual(
            [item[2] for item in variants],
            ["high.m3u8", "middle.m3u8", "low.m3u8"],
        )

    def test_equal_bandwidth_preserves_original_order(self):
        lines = [
            "#EXTM3U",
            "#EXT-X-STREAM-INF:BANDWIDTH=100",
            "first.m3u8",
            "#EXT-X-STREAM-INF:BANDWIDTH=100",
            "second.m3u8",
        ]
        variants = validator._parse_master_variants(lines)
        self.assertEqual(
            [item[2] for item in variants],
            ["first.m3u8", "second.m3u8"],
        )

    def test_finds_first_ts_segment(self):
        segment = validator._first_media_segment([
            "#EXTM3U",
            "#EXTINF:5,",
            "segment.ts",
            "next.ts",
        ])
        self.assertEqual(segment, "segment.ts")

    def test_rejects_fmp4_segment(self):
        segment = validator._first_media_segment([
            "#EXTM3U",
            "#EXTINF:5,",
            "segment.m4s",
        ])
        self.assertIsNone(segment)

    def test_rejects_playlist_without_segment(self):
        segment = validator._first_media_segment([
            "#EXTM3U",
            "#EXT-X-ENDLIST",
        ])
        self.assertIsNone(segment)


class TestValidateOne(unittest.IsolatedAsyncioTestCase):

    async def test_validates_ts_candidate(self):
        candidate = make_candidate()
        response = make_network_result(make_ts_data())

        with patch(
            "validator.network.request",
            new_callable=AsyncMock,
            return_value=response,
        ):
            result = await validator._validate_one(candidate)

        self.assertTrue(result.passed)
        self.assertTrue(result.completed)
        self.assertEqual(result.stream_type, StreamType.TS)

    async def test_rejects_ts_without_sync(self):
        candidate = make_candidate()
        response = make_network_result(bytes(940))

        with patch(
            "validator.network.request",
            new_callable=AsyncMock,
            return_value=response,
        ):
            result = await validator._validate_one(candidate)

        self.assertFalse(result.passed)
        self.assertTrue(result.completed)
        self.assertEqual(result.stream_type, StreamType.TS)

    async def test_rejects_failed_http_request(self):
        candidate = make_candidate()
        response = make_network_result(
            success=False,
            status_code=503,
            error="HTTP unavailable",
        )

        with patch(
            "validator.network.request",
            new_callable=AsyncMock,
            return_value=response,
        ):
            result = await validator._validate_one(candidate)

        self.assertFalse(result.passed)
        self.assertTrue(result.completed)

    async def test_timeout_returns_incomplete_result(self):
        with patch(
            "validator.network.request",
            new_callable=AsyncMock,
            side_effect=asyncio.TimeoutError,
        ):
            result = await validator._validate_one(make_candidate())

        self.assertFalse(result.passed)
        self.assertFalse(result.completed)
        self.assertEqual(result.stream_type, StreamType.UNKNOWN)

    async def test_validates_hls_media_playlist_and_segment(self):
        candidate = make_candidate("https://example.com/live.m3u8")
        playlist = make_network_result(
            b"#EXTM3U\n#EXTINF:5,\nsegment.ts\n",
            url=candidate.url,
            content_type="application/vnd.apple.mpegurl",
        )
        segment = make_network_result(
            make_ts_data(),
            url="https://example.com/segment.ts",
        )

        with patch(
            "validator.network.request",
            new_callable=AsyncMock,
            side_effect=[playlist, segment],
        ) as request:
            result = await validator._validate_one(candidate)

        self.assertTrue(result.passed)
        self.assertTrue(result.completed)
        self.assertEqual(result.stream_type, StreamType.HLS)
        self.assertEqual(request.await_count, 2)
        self.assertEqual(
            request.await_args_list[1].args[0],
            "https://example.com/segment.ts",
        )

    async def test_hls_playlist_failure_reports_http_status(self):
        candidate = make_candidate("https://example.com/live.m3u8")
        response = make_network_result(
            url=candidate.url,
            success=False,
            status_code=403,
            error="Forbidden",
        )

        with patch(
            "validator.network.request",
            new_callable=AsyncMock,
            return_value=response,
        ):
            result = await validator._validate_one(candidate)

        self.assertFalse(result.passed)
        self.assertEqual(result.reason, "HTTP status 403: Forbidden")

    async def test_hls_variant_failure_reports_http_status(self):
        candidate = make_candidate("https://example.com/master.m3u8")
        master = make_network_result(
            b"#EXTM3U\n"
            b"#EXT-X-STREAM-INF:BANDWIDTH=1000000\n"
            b"variant.m3u8\n",
            url=candidate.url,
        )
        variant = make_network_result(
            url="https://example.com/variant.m3u8",
            success=False,
            status_code=404,
            error="Not Found",
        )

        with patch(
            "validator.network.request",
            new_callable=AsyncMock,
            side_effect=[master, variant],
        ):
            result = await validator._validate_one(candidate)

        self.assertFalse(result.passed)
        self.assertEqual(result.reason, "HTTP status 404: Not Found")

    async def test_hls_segment_failure_reports_http_status(self):
        candidate = make_candidate("https://example.com/live.m3u8")
        playlist = make_network_result(
            b"#EXTM3U\n#EXTINF:5,\nsegment.ts\n",
            url=candidate.url,
        )
        segment = make_network_result(
            url="https://example.com/segment.ts",
            success=False,
            status_code=500,
            error="Internal Server Error",
        )

        with patch(
            "validator.network.request",
            new_callable=AsyncMock,
            side_effect=[playlist, segment],
        ):
            result = await validator._validate_one(candidate)

        self.assertFalse(result.passed)
        self.assertEqual(
            result.reason,
            "HTTP status 500: Internal Server Error",
        )

    async def test_hls_bad_status_line_error_is_not_duplicated(self):
        candidate = make_candidate("https://example.com/live.m3u8")
        response = make_network_result(
            url=candidate.url,
            success=False,
            status_code=400,
            error="Bad status line (status=400)",
        )

        with patch(
            "validator.network.request",
            new_callable=AsyncMock,
            return_value=response,
        ):
            result = await validator._validate_one(candidate)

        self.assertFalse(result.passed)
        self.assertEqual(
            result.reason,
            "Bad status line (status=400)",
        )

    async def test_rejects_encrypted_hls_without_segment_request(self):
        candidate = make_candidate("https://example.com/live.m3u8")
        playlist = make_network_result(
            b"#EXTM3U\n"
            b"#EXT-X-KEY:METHOD=AES-128,URI=\"key.bin\"\n"
            b"#EXTINF:5,\nsegment.ts\n",
            url=candidate.url,
        )

        with patch(
            "validator.network.request",
            new_callable=AsyncMock,
            return_value=playlist,
        ) as request:
            result = await validator._validate_one(candidate)

        self.assertFalse(result.passed)
        self.assertTrue(result.completed)
        self.assertEqual(result.stream_type, StreamType.HLS)
        self.assertEqual(request.await_count, 1)


class TestValidateCandidates(unittest.IsolatedAsyncioTestCase):

    async def test_empty_input_returns_empty_tuple(self):
        result = await validator.validate_candidates(())
        self.assertEqual(result, ())

    async def test_rejects_non_candidate_input(self):
        with self.assertRaises(TypeError):
            await validator.validate_candidates(("not a candidate",))

    async def test_preserves_input_order(self):
        candidates = (
            make_candidate("https://example.com/first.ts", 0),
            make_candidate("https://example.com/second.ts", 1),
        )

        async def fake_validate(candidate):
            await asyncio.sleep(0)
            return ValidationResult(
                candidate=candidate,
                passed=True,
                stream_type=StreamType.TS,
                completed=True,
            )

        with patch(
            "validator._validate_one",
            new_callable=AsyncMock,
            side_effect=fake_validate,
        ):
            results = await validator.validate_candidates(candidates)

        self.assertEqual(
            [item.candidate.url for item in results],
            [item.url for item in candidates],
        )

    async def test_detection_budget_preserves_completed_results_and_marks_pending(self):
        candidates = (
            make_candidate("https://example.com/first.ts", 0),
            make_candidate("https://example.com/second.ts", 1),
            make_candidate("https://example.com/third.ts", 2),
        )

        second_started = asyncio.Event()
        second_cancelled = asyncio.Event()
        called_urls = []

        async def fake_validate(candidate):
            called_urls.append(candidate.url)

            if candidate.url.endswith("first.ts"):
                return ValidationResult(
                    candidate=candidate,
                    passed=True,
                    stream_type=StreamType.TS,
                    completed=True,
                )

            if candidate.url.endswith("second.ts"):
                second_started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    second_cancelled.set()

            self.fail("A queued candidate must not start after budget expiry.")

        with (
            patch(
                "validator._validate_one",
                new_callable=AsyncMock,
                side_effect=fake_validate,
            ),
            patch.multiple(
                "validator.config",
                MAX_CONCURRENT_VALIDATIONS=1,
                VALIDATION_WAITING_QUEUE_LIMIT=1,
                DETECTION_BUDGET_SECONDS=0.1,
                CANDIDATE_VALIDATION_BUDGET_SECONDS=8,
            ),
        ):
            results = await validator.validate_candidates(candidates)

        self.assertTrue(second_started.is_set())
        self.assertTrue(second_cancelled.is_set())

        self.assertEqual(
            [item.candidate.url for item in results],
            [item.url for item in candidates],
        )

        self.assertTrue(results[0].completed)
        self.assertTrue(results[0].passed)

        for result in results[1:]:
            self.assertFalse(result.completed)
            self.assertFalse(result.passed)
            self.assertEqual(
                result.reason,
                "Detection stage budget exhausted.",
            )

        self.assertEqual(
            called_urls,
            [
                "https://example.com/first.ts",
                "https://example.com/second.ts",
            ],
        )

    async def test_external_cancellation_propagates_and_cancels_active_work(self):
        candidates = (
            make_candidate("https://example.com/first.ts", 0),
            make_candidate("https://example.com/second.ts", 1),
            make_candidate("https://example.com/third.ts", 2),
        )

        second_started = asyncio.Event()
        second_cancelled = asyncio.Event()
        called_urls = []

        async def fake_validate(candidate):
            called_urls.append(candidate.url)

            if candidate.url.endswith("first.ts"):
                return ValidationResult(
                    candidate=candidate,
                    passed=True,
                    stream_type=StreamType.TS,
                    completed=True,
                )

            if candidate.url.endswith("second.ts"):
                second_started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    second_cancelled.set()

            self.fail("A queued candidate must not start after cancellation.")

        with (
            patch(
                "validator._validate_one",
                new_callable=AsyncMock,
                side_effect=fake_validate,
            ),
            patch.multiple(
                "validator.config",
                MAX_CONCURRENT_VALIDATIONS=1,
                VALIDATION_WAITING_QUEUE_LIMIT=1,
                DETECTION_BUDGET_SECONDS=30,
                CANDIDATE_VALIDATION_BUDGET_SECONDS=8,
            ),
        ):
            validation_task = asyncio.create_task(
                validator.validate_candidates(candidates)
            )

            await asyncio.wait_for(
                second_started.wait(),
                timeout=3,
            )

            validation_task.cancel()

            with self.assertRaises(asyncio.CancelledError):
                await validation_task

        self.assertTrue(second_cancelled.is_set())

        self.assertEqual(
            called_urls,
            [
                "https://example.com/first.ts",
                "https://example.com/second.ts",
            ],
        )
