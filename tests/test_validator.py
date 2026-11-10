"""Business tests for IPTV candidate validation."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import config
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

    def test_accepts_five_ts_sync_bytes(self):
        self.assertTrue(validator._has_ts_sync(make_ts_data()))

    def test_rejects_missing_ts_sync(self):
        self.assertFalse(validator._has_ts_sync(b"\x47" * 940))

    def test_rejects_non_bytes_ts_data(self):
        self.assertFalse(validator._has_ts_sync("not bytes"))

    def test_accepts_sync_at_nonzero_offset(self):
        data = bytearray(941)

        for offset in (7, 195, 383, 571, 759):
            data[offset] = 0x47

        self.assertTrue(validator._has_ts_sync(bytes(data)))


class TestHLSHelpers(unittest.TestCase):

    def test_detects_hls_url_case_insensitively(self):
        self.assertTrue(
            validator._is_hls_url("https://example.com/LIVE.M3U8")
        )

    def test_rejects_non_hls_url(self):
        self.assertFalse(
            validator._is_hls_url("https://example.com/live.ts")
        )

    def test_detects_hls_content_by_playlist_header(self):
        result = make_network_result(
            b"\xef\xbb\xbf #EXTM3U\n#EXTINF:5,\nsegment.ts\n"
        )
        self.assertTrue(validator._is_hls_content(result))

    def test_detects_hls_content_by_content_type(self):
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

    def test_playlist_text_rejects_failed_http_result(self):
        result = make_network_result(
            b"#EXTM3U\n",
            success=False,
            status_code=500,
        )
        self.assertIsNone(validator._playlist_text(result))

    def test_parses_quoted_hls_attributes(self):
        attributes = validator._parse_attributes(
            'BANDWIDTH=1200000,RESOLUTION="1280x720"'
        )
        self.assertEqual(attributes["BANDWIDTH"], "1200000")
        self.assertEqual(attributes["RESOLUTION"], "1280x720")

    def test_rejects_encrypted_hls_key(self):
        error = validator._check_unsupported_tags([
            '#EXT-X-KEY:METHOD=AES-128,URI="key.bin"'
        ])
        self.assertIsNotNone(error)

    def test_allows_hls_key_method_none(self):
        error = validator._check_unsupported_tags([
            "#EXT-X-KEY:METHOD=NONE"
        ])
        self.assertIsNone(error)

    def test_rejects_hls_session_key(self):
        error = validator._check_unsupported_tags([
            '#EXT-X-SESSION-KEY:METHOD=AES-128,URI="key.bin"'
        ])
        self.assertIsNotNone(error)

    def test_rejects_hls_fmp4_map(self):
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

    def test_master_variant_equal_bandwidth_keeps_original_order(self):
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

    def test_missing_bandwidth_is_treated_as_zero(self):
        lines = [
            "#EXTM3U",
            "#EXT-X-STREAM-INF",
            "unknown.m3u8",
            "#EXT-X-STREAM-INF:BANDWIDTH=10",
            "known.m3u8",
        ]

        variants = validator._parse_master_variants(lines)

        self.assertEqual(
            [item[2] for item in variants],
            ["known.m3u8", "unknown.m3u8"],
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
        response = make_network_result(b"\x00" * 940)

        with patch(
            "validator.network.request",
            new_callable=AsyncMock,
            return_value=response,
        ):
            result = await validator._validate_one(candidate)

        self.assertFalse(result.passed)
        self.assertTrue(result.completed)
        self.assertEqual(result.stream_type, StreamType.TS)

    async def test_rejects_failed_ts_http_request(self):
        candidate = make_candidate()
        response = make_network_result(
            b"",
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
        candidate = make_candidate()

        with patch(
            "validator.network.request",
            new_callable=AsyncMock,
            side_effect=asyncio.TimeoutError,
        ):
            result = await validator._validate_one(candidate)

        self.assertFalse(result.passed)
        self.assertFalse(result.completed)
        self.assertEqual(result.stream_type, StreamType.UNKNOWN)

    async def test_validates_hls_media_playlist_and_segment(self):
        candidate = make_candidate("https://example.com/live.m3u8")
        playlist = (
            b"#EXTM3U\n"
            b"#EXTINF:5,\n"
            b"segment.ts\n"
        )
        playlist_result = make_network_result(
            playlist,
            url=candidate.url,
            content_type="application/vnd.apple.mpegurl",
        )
        segment_result = make_network_result(
            make_ts_data(),
            url="https://example.com/segment.ts",
        )

        with patch(
            "validator.network.request",
            new_callable=AsyncMock,
            side_effect=[playlist_result, segment_result],
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

    async def test_rejects_encrypted_hls_without_fetching_segment(self):
        candidate = make_candidate("https://example.
