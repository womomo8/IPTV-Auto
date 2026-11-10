
"""Unit tests for source URL normalization and index parsing."""

import unittest
from unittest.mock import patch

import sources
from models import DownloadResult, SourceKind, SourceRecord


class TestNormalizeSourceUrl(unittest.TestCase):

    def test_normalizes_scheme_host_default_port_and_fragment(self):
        self.assertEqual(
            sources.normalize_source_url(
                "HTTPS://Example.COM:443/live.m3u?token=abc#section"
            ),
            "https://example.com/live.m3u?token=abc",
        )

    def test_removes_http_default_port(self):
        self.assertEqual(
            sources.normalize_source_url("HTTP://Example.COM:80"),
            "http://example.com/",
        )

    def test_preserves_non_default_port_path_and_query(self):
        self.assertEqual(
            sources.normalize_source_url(
                "https://Example.COM:8443/a/b?x=1#part"
            ),
            "https://example.com:8443/a/b?x=1",
        )

    def test_rejects_empty_or_non_string_input(self):
        for value in ("", "   ", None, 123):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    sources.normalize_source_url(value)

    def test_rejects_unsupported_scheme_and_missing_host(self):
        for value in (
            "ftp://example.com/live",
            "file:///tmp/live",
            "https:///live",
            "//example.com/live",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    sources.normalize_source_url(value)

    def test_rejects_userinfo(self):
        with self.assertRaises(ValueError):
            sources.normalize_source_url(
                "https://user:password@example.com/live"
            )

    def test_rejects_invalid_ports(self):
        for value in (
            "http://example.com:0/live",
            "http://example.com:65536/live",
            "http://example.com:invalid/live",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    sources.normalize_source_url(value)

    def test_rejects_whitespace_and_control_characters(self):
        for value in (
            "https://example.com/live path",
            "https://example.com/live\npath",
            "https://example.com/live\tpath",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    sources.normalize_source_url(value)


class TestBuildSourceList(unittest.TestCase):

    def test_preserves_priority_and_removes_global_duplicates(self):
        with (
            patch.object(
                sources.config,
                "MANUAL_STREAM_URLS",
                ["https://EXAMPLE.com/live#one"],
            ),
            patch.object(
                sources.config,
                "MANUAL_SUBSCRIPTION_SOURCES",
                [
                    "https://example.com/live",
                    "https://manual.example/sub.m3u",
                ],
            ),
        ):
            result = sources.build_source_list(
                [
                    "https://manual.example/sub.m3u",
                    "https://auto.example/index.m3u",
                ]
            )

        self.assertEqual(
            tuple(item.kind for item in result),
            (
                SourceKind.MANUAL_STREAM,
                SourceKind.MANUAL_SUBSCRIPTION,
                SourceKind.AUTO_INDEX,
            ),
        )
        self.assertEqual(
            tuple(item.url for item in result),
            (
                "https://example.com/live",
                "https://manual.example/sub.m3u",
                "https://auto.example/index.m3u",
            ),
        )

    def test_duplicate_urls_are_kept_only_once(self):
        with (
            patch.object(
                sources.config,
                "MANUAL_STREAM_URLS",
                [],
            ),
            patch.object(
                sources.config,
                "MANUAL_SUBSCRIPTION_SOURCES",
                [
                    "https://example.com/sub",
                    "https://EXAMPLE.com:443/sub#top",
                ],
            ),
        ):
            result = sources.build_source_list()

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0].kind,
            SourceKind.MANUAL_SUBSCRIPTION,
        )


class TestParseIndexDownload(unittest.TestCase):

    def setUp(self):
        self.index_source = SourceRecord(
            url="https://example.com/index.txt",
            kind=SourceKind.AUTO_INDEX,
            order=1,
        )

    def make_result(
        self,
        content=b"",
        *,
        success=True,
        truncated=False,
        source=None,
    ):
        return DownloadResult(
            source=source or self.index_source,
            success=success,
            content=content,
            truncated=truncated,
        )

    def test_parses_valid_urls_and_ignores_blank_lines_and_comments(self):
        content = (
            b"# index comment\n"
            b"\n"
            b"https://one.example/live.m3u\n"
            b"  \n"
            b"https://two.example/live.m3u\n"
        )

        result = sources.parse_index_download(
            self.make_result(content)
        )

        self.assertEqual(result.invalid_count, 0)
        self.assertEqual(
            tuple(item.url for item in result.sources),
            (
                "https://one.example/live.m3u",
                "https://two.example/live.m3u",
            ),
        )
        self.assertEqual(
            tuple(item.order for item in result.sources),
            (3, 5),
        )
        self.assertTrue(
            all(
                item.kind == SourceKind.AUTO_SUBSCRIPTION
                for item in result.sources
            )
        )

    def test_skips_invalid_and_duplicate_lines(self):
        content = (
            b"https://one.example/live.m3u\n"
            b"https://ONE.example:443/live.m3u#duplicate\n"
            b"ftp://invalid.example/live\n"
            b"https://two.example/live.m3u\n"
        )

        result = sources.parse_index_download(
            self.make_result(content)
        )

        self.assertEqual(result.invalid_count, 1)
        self.assertEqual(
            tuple(item.url for item in result.sources),
            (
                "https://one.example/live.m3u",
                "https://two.example/live.m3u",
            ),
        )
        self.assertTrue(result.messages)

    def test_rejects_failed_or_truncated_download(self):
        failed = sources.parse_index_download(
            self.make_result(
                b"https://one.example/live.m3u",
                success=False,
            )
        )
        truncated = sources.parse_index_download(
            self.make_result(
                b"https://one.example/live.m3u",
                truncated=True,
            )
        )

        self.assertEqual(failed.sources, ())
        self.assertEqual(truncated.sources, ())
        self.assertTrue(failed.messages)
        self.assertTrue(truncated.messages)

    def test_rejects_invalid_utf8(self):
        result = sources.parse_index_download(
            self.make_result(b"\xff\xfe")
        )

        self.assertEqual(result.sources, ())
        self.assertTrue(result.messages)

    def test_rejects_index_over_size_limit(self):
        with patch.object(
            sources.config,
            "MAX_INDEX_BYTES",
            4,
        ):
            result = sources.parse_index_download(
                self.make_result(b"12345")
            )

        self.assertEqual(result.sources, ())
        self.assertTrue(result.messages)

    def test_rejects_download_from_non_index_source(self):
        wrong_source = SourceRecord(
            url="https://example.com/sub.m3u",
            kind=SourceKind.MANUAL_SUBSCRIPTION,
            order=1,
        )

        with self.assertRaises(ValueError):
            sources.parse_index_download(
                self.make_result(
                    b"https://one.example/live.m3u",
                    source=wrong_source,
                )
            )


if __name__ == "__main__":
    unittest.main()
