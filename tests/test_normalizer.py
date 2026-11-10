
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


