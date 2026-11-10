
"""Business tests for subscription normalization and candidate allocation."""

import unittest
from unittest.mock import patch

import normalizer
from models import DownloadResult, SourceKind, SourceRecord


def make_source(url, kind=SourceKind.AUTO_SUBSCRIPTION, order=1):
    return SourceRecord(url=url, kind=kind, order=order)


def make_download(source, content, success=True, truncated=False):
    return DownloadResult(
        source=source,
        success=success,
        content=content,
        status_code=200 if success else None,
        truncated=truncated,
    )


def make_m3u(*records):
    lines = ["#EXTM3U"]
    for attributes, name, url in records:
        lines.append(f"#EXTINF:-1 {attributes},{name}")
        lines.append(url)
    return "\n".join(lines).encode("utf-8")


class TestSubscriptionParsing(unittest.TestCase):

    def test_parses_supported_attributes_and_channel_name(self):
        source = make_source(
            "https://example.com/list.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
        )
        content = (
            '#EXTINF:-1 tvg-id="channel.id" '
            'tvg-name="Display Name" group-title="Sports",'
            'Channel, Extra\n'
            'https://example.com/live.ts\n'
        ).encode("utf-8")

        candidates = normalizer.normalize_candidates(
            (make_download(source, content),),
            manual_stream_urls=(),
        )

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.name, "Channel, Extra")
        self.assertEqual(candidate.tvg_id, "channel.id")
        self.assertEqual(candidate.tvg_name, "Display Name")
        self.assertEqual(candidate.group_title, "Sports")
        self.assertEqual(candidate.url, "https://example.com/live.ts")

    def test_uses_extgrp_when_group_title_is_missing(self):
        source = make_source(
            "https://example.com/list.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
        )
        content = (
            "#EXTGRP:Sports\n"
            "#EXTINF:-1,Channel One\n"
            "https://example.com/one.ts\n"
            "#EXTINF:-1,Channel Two\n"
            "https://example.com/two.ts\n"
        ).encode("utf-8")

        candidates = normalizer.normalize_candidates(
            (make_download(source, content),),
            manual_stream_urls=(),
        )

        self.assertEqual(len(candidates), 2)
        self.assertEqual(
            [item.group_title for item in candidates],
            ["Sports", "Sports"],
        )

    def test_explicit_group_title_overrides_extgrp(self):
        source = make_source(
            "https://example.com/list.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
        )
        content = (
            '#EXTGRP:Sports\n'
            '#EXTINF:-1 group-title="News",Channel\n'
            'https://example.com/live.ts\n'
        ).encode("utf-8")

        candidates = normalizer.normalize_candidates(
            (make_download(source, content),),
            manual_stream_urls=(),
        )

        self.assertEqual(candidates[0].group_title, "News")

    def test_ignores_unknown_attributes(self):
        source = make_source(
            "https://example.com/list.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
        )
        content = (
            '#EXTINF:-1 custom-value="ignored" '
            'tvg-id="known",Channel\n'
            'https://example.com/live.ts\n'
        ).encode("utf-8")

        candidates = normalizer.normalize_candidates(
            (make_download(source, content),),
            manual_stream_urls=(),
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].tvg_id, "known")

    def test_skips_invalid_extinf_and_empty_channel_name(self):
        source = make_source(
            "https://example.com/list.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
        )
        content = (
            "#EXTINF:-1 missing-comma\n"
            "https://example.com/invalid.ts\n"
            "#EXTINF:-1,\n"
            "https://example.com/empty.ts\n"
            "#EXTINF:-1,Valid Channel\n"
            "https://example.com/valid.ts\n"
        ).encode("utf-8")

        candidates = normalizer.normalize_candidates(
            (make_download(source, content),),
            manual_stream_urls=(),
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].name, "Valid Channel")

    def test_skips_invalid_stream_urls(self):
        source = make_source(
            "https://example.com/list.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
        )
        content = (
            "#EXTINF:-1,Relative\n"
            "/relative/live.ts\n"
            "#EXTINF:-1,Unsupported\n"
            "ftp://example.com/live.ts\n"
            "#EXTINF:-1,Valid\n"
            "https://example.com/live.ts\n"
        ).encode("utf-8")

        candidates = normalizer.normalize_candidates(
            (make_download(source, content),),
            manual_stream_urls=(),
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].name, "Valid")

    def test_ignores_invalid_utf8_line_without_stopping_parsing(self):
        source = make_source(
            "https://example.com/list.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
        )
        content = (
            b"\xff\xfe\n"
            b"#EXTINF:-1,Valid\n"
            b"https://example.com/valid.ts\n"
        )

        candidates = normalizer.normalize_candidates(
            (make_download(source, content),),
            manual_stream_urls=(),
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].name, "Valid")

    def test_ignores_non_subscription_download_sources(self):
        source = make_source(
            "https://example.com/index.txt",
            SourceKind.AUTO_INDEX,
        )
        content = make_m3u(
            ("", "Channel", "https://example.com/live.ts"),
        )

        candidates = normalizer.normalize_candidates(
            (make_download(source, content),),
            manual_stream_urls=(),
        )

        self.assertEqual(candidates, ())

    def test_skips_failed_download(self):
        source = make_source(
            "https://example.com/list.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
        )
        content = make_m3u(
            ("", "Channel", "https://example.com/live.ts"),
        )

        candidates = normalizer.normalize_candidates(
            (
                make_download(
                    source,
                    content,
                    success=False,
                ),
            ),
            manual_stream_urls=(),
        )

        self.assertEqual(candidates, ())

    def test_skips_truncated_download(self):
        source = make_source(
            "https://example.com/list.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
        )
        content = make_m3u(
            ("", "Channel", "https://example.com/live.ts"),
        )

        candidates = normalizer.normalize_candidates(
            (
                make_download(
                    source,
                    content,
                    truncated=True,
                ),
            ),
            manual_stream_urls=(),
        )

        self.assertEqual(candidates, ())


class TestCandidatePriorityAndOrdering(unittest.TestCase):

    def test_manual_stream_has_highest_priority(self):
        source = make_source(
            "https://example.com/manual.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
        )
        content = make_m3u(
            ("", "Subscription", "https://example.com/live.ts"),
        )

        candidates = normalizer.normalize_candidates(
            (make_download(source, content),),
            manual_stream_urls=(
                "https://EXAMPLE.com:443/live.ts#manual",
            ),
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(
            candidates[0].source_kind,
            SourceKind.MANUAL_STREAM,
        )

    def test_manual_subscription_precedes_automatic(self):
        automatic = make_source(
            "https://example.com/auto.m3u",
            SourceKind.AUTO_SUBSCRIPTION,
            1,
        )
        manual = make_source(
            "https://example.com/manual.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
            2,
        )

        auto_content = make_m3u(
            ("", "Automatic", "https://example.com/auto.ts"),
        )
        manual_content = make_m3u(
            ("", "Manual", "https://example.com/manual.ts"),
        )

        candidates = normalizer.normalize_candidates(
            (
                make_download(automatic, auto_content),
                make_download(manual, manual_content),
            ),
            manual_stream_urls=(),
        )

        self.assertEqual(
            [item.name for item in candidates],
            ["Manual", "Automatic"],
        )

    def test_source_order_is_stable(self):
        later = make_source(
            "https://example.com/later.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
            2,
        )
        earlier = make_source(
            "https://example.com/earlier.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
            1,
        )

        later_content = make_m3u(
            ("", "Later", "https://example.com/later.ts"),
        )
        earlier_content = make_m3u(
            ("", "Earlier", "https://example.com/earlier.ts"),
        )

        candidates = normalizer.normalize_candidates(
            (
                make_download(later, later_content),
                make_download(earlier, earlier_content),
            ),
            manual_stream_urls=(),
        )

        self.assertEqual(
            [item.name for item in candidates],
            ["Earlier", "Later"],
        )

    def test_item_order_preserves_record_order(self):
        source = make_source(
            "https://example.com/list.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
        )
        content = make_m3u(
            ("", "First", "https://example.com/first.ts"),
            ("", "Second", "https://example.com/second.ts"),
        )

        candidates = normalizer.normalize_candidates(
            (make_download(source, content),),
            manual_stream_urls=(),
        )

        self.assertEqual(
            [item.item_order for item in candidates],
            [1, 2],
        )


class TestCandidateDeduplicationAndLimits(unittest.TestCase):

    def test_normalized_duplicate_urls_are_kept_once(self):
        source = make_source(
            "https://example.com/list.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
        )
        content = make_m3u(
            ("", "First", "https://EXAMPLE.com:443/live.ts#one"),
            ("", "Second", "https://example.com/live.ts#two"),
        )

        candidates = normalizer.normalize_candidates(
            (make_download(source, content),),
            manual_stream_urls=(),
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].name, "First")
        self.assertEqual(
            candidates[0].url,
            "https://example.com/live.ts",
        )

    def test_duplicate_does_not_consume_source_limit(self):
        first = make_source(
            "https://example.com/first.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
            1,
        )
        second = make_source(
            "https://example.com/second.m3u",
            SourceKind.AUTO_SUBSCRIPTION,
            2,
        )

        first_content = make_m3u(
            ("", "First", "https://example.com/shared.ts"),
        )
        second_content = make_m3u(
            ("", "Duplicate", "https://EXAMPLE.com:443/shared.ts#x"),
            ("", "Second", "https://example.com/second.ts"),
        )

        candidates = normalizer.normalize_candidates(
            (
                make_download(first, first_content),
                make_download(second, second_content),
            ),
            manual_stream_urls=(),
        )

        self.assertEqual(
            [item.name for item in candidates],
            ["First", "Second"],
        )

    def test_enforces_per_source_candidate_limit(self):
        first = make_source(
            "https://example.com/first.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
            1,
        )
        second = make_source(
            "https://example.com/second.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
            2,
        )

        first_content = make_m3u(
            ("", "A1", "https://example.com/a1.ts"),
            ("", "A2", "https://example.com/a2.ts"),
            ("", "A3", "https://example.com/a3.ts"),
        )
        second_content = make_m3u(
            ("", "B1", "https://example.com/b1.ts"),
            ("", "B2", "https://example.com/b2.ts"),
            ("", "B3", "https://example.com/b3.ts"),
        )

        with patch.object(
            normalizer.config,
            "MAX_CANDIDATES_PER_SOURCE",
            2,
        ):
            candidates = normalizer.normalize_candidates(
                (
                    make_download(first, first_content),
                    make_download(second, second_content),
                ),
                manual_stream_urls=(),
            )

        self.assertEqual(
            [item.name for item in candidates],
            ["A1", "A2", "B1", "B2"],
        )

    def test_enforces_global_candidate_limit(self):
        source = make_source(
            "https://example.com/list.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
        )
        content = make_m3u(
            ("", "One", "https://example.com/one.ts"),
            ("", "Two", "https://example.com/two.ts"),
            ("", "Three", "https://example.com/three.ts"),
        )

        with patch.object(
            normalizer.config,
            "MAX_CANDIDATES_TOTAL",
            2,
        ):
            candidates = normalizer.normalize_candidates(
                (make_download(source, content),),
                manual_stream_urls=(),
            )

        self.assertEqual(
            [item.name for item in candidates],
            ["One", "Two"],
        )

    def test_manual_streams_count_toward_global_limit(self):
        source = make_source(
            "https://example.com/list.m3u",
            SourceKind.MANUAL_SUBSCRIPTION,
        )
        content = make_m3u(
            ("", "Subscription", "https://example.com/sub.ts"),
        )

        with patch.object(
            normalizer.config,
            "MAX_CANDIDATES_TOTAL",
            2,
        ):
            candidates = normalizer.normalize_candidates(
                (make_download(source, content),),
                manual_stream_urls=(
                    "https://example.com/manual-one.ts",
                    "https://example.com/manual-two.ts",
                ),
            )

        self.assertEqual(len(candidates), 2)
        self.assertTrue(
            all(
                item.source_kind == SourceKind.MANUAL_STREAM
                for item in candidates
            )
        )

    def test_rejects_invalid_download_results_argument(self):
        with self.assertRaises(TypeError):
            normalizer.normalize_candidates(
                "not a sequence",
                manual_stream_urls=(),
            )

    def test_rejects_non_download_result_items(self):
        with self.assertRaises(TypeError):
            normalizer.normalize_candidates(
                ("invalid",),
                manual_stream_urls=(),
            )

    def test_rejects_invalid_manual_stream_argument(self):
        with self.assertRaises(TypeError):
            normalizer.normalize_candidates(
                (),
                manual_stream_urls="https://example.com/live.ts",
            )

    def test_rejects_non_positive_candidate_limits(self):
        with patch.object(
            normalizer.config,
            "MAX_CANDIDATES_PER_SOURCE",
            0,
        ):
            with self.assertRaises(ValueError):
                normalizer.normalize_candidates(
                    (),
                    manual_stream_urls=(),
                )

        with patch.object(
            normalizer.config,
            "MAX_CANDIDATES_TOTAL",
            0,
        ):
            with self.assertRaises(ValueError):
                normalizer.normalize_candidates(
                    (),
                    manual_stream_urls=(),
                )


class TestChannelTxtParsing(unittest.TestCase):

    def setUp(self):
        self.source = make_source(
            "https://example.com/channels.txt",
            SourceKind.MANUAL_SUBSCRIPTION,
        )

    def parse(self, content):
        return normalizer.normalize_candidates(
            (make_download(self.source, content),),
            manual_stream_urls=(),
        )

    def test_parses_utf8_txt(self):
        content = (
            "央视,#genre#\n"
            "CCTV1综合,http://example.com/1.ts\n"
        ).encode("utf-8")

        candidates = self.parse(content)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].name, "CCTV1综合")
        self.assertEqual(candidates[0].group_title, "央视")

    def test_parses_utf8_bom_txt(self):
        content = (
            "\ufeff央视,#genre#\n"
            "CCTV1综合,http://example.com/1.ts\n"
        ).encode("utf-8")

        candidates = self.parse(content)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].name, "CCTV1综合")

    def test_parses_gb18030_txt(self):
        content = (
            "央视,#genre#\n"
            "CCTV1综合,http://example.com/1.ts\n"
        ).encode("gb18030")

        candidates = self.parse(content)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].name, "CCTV1综合")
        self.assertEqual(candidates[0].group_title, "央视")

    def test_inherits_and_switches_genres(self):
        content = (
            "央视,#genre#\n"
            "CCTV1,http://example.com/1.ts\n"
            "CCTV2,http://example.com/2.ts\n"
            "卫视,#genre#\n"
            "湖南卫视,http://example.com/hunan.ts\n"
        ).encode("utf-8")

        candidates = self.parse(content)

        self.assertEqual(
            [item.group_title for item in candidates],
            ["央视", "央视", "卫视"],
        )

    def test_ignores_group_marker(self):
        content = (
            "频道,#group#\n"
            "CCTV1,http://example.com/1.ts\n"
        ).encode("utf-8")

        candidates = self.parse(content)

        self.assertEqual(len(candidates), 1)
        self.assertIsNone(candidates[0].group_title)

    def test_ignores_comments_and_empty_lines(self):
        content = (
            "\n"
            "// this is a comment\n"
            "央视,#genre#\n"
            "\n"
            "CCTV1,http://example.com/1.ts\n"
        ).encode("utf-8")

        candidates = self.parse(content)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].name, "CCTV1")

    def test_splits_only_at_first_comma(self):
        content = (
            "CCTV1,http://example.com/live.ts?token=a,b,c\n"
        ).encode("utf-8")

        candidates = self.parse(content)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(
            candidates[0].url,
            "http://example.com/live.ts?token=a,b,c",
        )

    def test_skips_invalid_records_without_stopping(self):
        content = (
            ",http://example.com/empty-name.ts\n"
            "NoURL,\n"
            "Relative,/live.ts\n"
            "Unsupported,ftp://example.com/live.ts\n"
            "Invalid line\n"
            "Valid,http://example.com/valid.ts\n"
        ).encode("utf-8")

        candidates = self.parse(content)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].name, "Valid")

    def test_txt_candidate_fields(self):
        content = (
            "体育,#genre#\n"
            "CCTV5,http://example.com/5.ts\n"
        ).encode("utf-8")

        candidates = self.parse(content)
        candidate = candidates[0]

        self.assertIsNone(candidate.tvg_id)
        self.assertIsNone(candidate.tvg_name)
        self.assertEqual(candidate.group_title, "体育")
        self.assertEqual(candidate.source_url, self.source.url)
        self.assertEqual(
            candidate.source_kind,
            SourceKind.MANUAL_SUBSCRIPTION,
        )

    def test_skips_content_that_cannot_be_decoded(self):
        content = b"\x81"

        candidates = self.parse(content)

        self.assertEqual(candidates, ())

    def test_m3u_does_not_fallback_to_gb18030(self):
        content = (
            b"#EXTM3U\n"
            b"#EXTINF:-1,"
            + "中文频道".encode("gb18030")
            + b"\n"
            b"http://example.com/live.ts\n"
        )

        candidates = self.parse(content)

        self.assertEqual(candidates, ())

    def test_m3u_still_parses_normally(self):
        content = (
            "#EXTM3U\n"
            '#EXTINF:-1 group-title="体育",CCTV5\n'
            "http://example.com/5.ts\n"
        ).encode("utf-8")

        candidates = self.parse(content)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].name, "CCTV5")
        self.assertEqual(candidates[0].group_title, "体育")

    def test_unrecognized_format_is_skipped(self):
        content = (
            "This is an ordinary text document.\n"
            "It has no channel records.\n"
        ).encode("utf-8")

        candidates = self.parse(content)

        self.assertEqual(candidates, ())

    def test_txt_duplicate_urls_are_deduplicated(self):
        content = (
            "First,http://EXAMPLE.com:80/live.ts#one\n"
            "Second,http://example.com/live.ts#two\n"
        ).encode("utf-8")

        candidates = self.parse(content)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].name, "First")
        self.assertEqual(
            candidates[0].url,
            "http://example.com/live.ts",
        )


if __name__ == "__main__":
    unittest.main()
