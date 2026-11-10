
"""Business tests for validated candidate filtering and M3U generation."""

import unittest

import filter as iptv_filter
from models import Candidate, SourceKind, StreamType, ValidationResult


def make_candidate(
    url,
    name="Channel",
    kind=SourceKind.AUTO_SUBSCRIPTION,
    source_order=1,
    item_order=1,
    tvg_id=None,
    tvg_name=None,
    group_title=None,
):
    return Candidate(
        url=url,
        name=name,
        source_kind=kind,
        source_order=source_order,
        item_order=item_order,
        tvg_id=tvg_id,
        tvg_name=tvg_name,
        group_title=group_title,
    )


def make_result(candidate, passed=True, completed=True):
    return ValidationResult(
        candidate=candidate,
        passed=passed,
        completed=completed,
        stream_type=StreamType.TS,
        reason=None if passed else "Test failure",
    )


class TestFilterEligibility(unittest.TestCase):

    def test_only_completed_passed_candidates_are_kept(self):
        valid = make_candidate("https://example.com/valid.ts", "Valid")
        failed = make_candidate("https://example.com/failed.ts", "Failed")
        incomplete = make_candidate(
            "https://example.com/incomplete.ts", "Incomplete"
        )

        result = iptv_filter.filter_candidates((
            make_result(valid),
            make_result(failed, passed=False),
            make_result(incomplete, passed=False, completed=False),
        ))

        self.assertEqual(result.channel_count, 1)
        self.assertIn("Valid", result.m3u_content)
        self.assertNotIn("Failed", result.m3u_content)
        self.assertNotIn("Incomplete", result.m3u_content)

    def test_empty_input_returns_valid_empty_m3u(self):
        result = iptv_filter.filter_candidates(())

        self.assertEqual(result.channel_count, 0)
        self.assertEqual(result.m3u_content, "#EXTM3U\n")

    def test_empty_channel_name_is_skipped(self):
        candidate = make_candidate("https://example.com/live.ts", "   ")
        result = iptv_filter.filter_candidates((make_result(candidate),))

        self.assertEqual(result.channel_count, 0)


class TestFilterOrderingAndDeduplication(unittest.TestCase):

    def test_source_priority_is_stable(self):
        automatic = make_candidate(
            "https://example.com/auto.ts",
            "Automatic",
            SourceKind.AUTO_SUBSCRIPTION,
        )
        manual = make_candidate(
            "https://example.com/manual.ts",
            "Manual",
            SourceKind.MANUAL_SUBSCRIPTION,
        )
        single = make_candidate(
            "https://example.com/single.ts",
            "Single",
            SourceKind.MANUAL_STREAM,
        )

        result = iptv_filter.filter_candidates((
            make_result(automatic),
            make_result(single),
            make_result(manual),
        ))

        self.assertEqual(
            result.m3u_content.splitlines()[1::2],
            [
                '#EXTINF:-1 tvg-name="Single",Single',
                '#EXTINF:-1 tvg-name="Manual",Manual',
                '#EXTINF:-1 tvg-name="Automatic",Automatic',
            ],
        )

    def test_source_order_and_item_order_are_stable(self):
        later = make_candidate(
            "https://example.com/later.ts",
            "Later",
            source_order=2,
        )
        first = make_candidate(
            "https://example.com/first.ts",
            "First",
            source_order=1,
            item_order=1,
        )
        second = make_candidate(
            "https://example.com/second.ts",
            "Second",
            source_order=1,
            item_order=2,
        )

        result = iptv_filter.filter_candidates((
            make_result(later),
            make_result(second),
            make_result(first),
        ))

        self.assertEqual(
            result.m3u_content.splitlines()[1::2],
            [
                '#EXTINF:-1 tvg-name="First",First',
                '#EXTINF:-1 tvg-name="Second",Second',
                '#EXTINF:-1 tvg-name="Later",Later',
            ],
        )

    def test_normalized_duplicate_urls_keep_highest_priority(self):
        manual = make_candidate(
            "https://example.com/live.ts",
            "Manual",
            SourceKind.MANUAL_SUBSCRIPTION,
        )
        automatic = make_candidate(
            "https://EXAMPLE.com:443/live.ts#fragment",
            "Automatic",
            SourceKind.AUTO_SUBSCRIPTION,
        )

        result = iptv_filter.filter_candidates((
            make_result(automatic),
            make_result(manual),
        ))

        self.assertEqual(result.channel_count, 1)
        self.assertIn(",Manual\n", result.m3u_content)
        self.assertNotIn(",Automatic\n", result.m3u_content)

    def test_same_channel_with_different_urls_is_kept_once(self):
        first = make_candidate(
            "https://example.com/one.ts",
            "Channel One",
            tvg_id="channel-1",
        )
        second = make_candidate(
            "https://example.com/two.ts",
            "Another Display Name",
            tvg_id=" channel-1 ",
            item_order=2,
        )

        result = iptv_filter.filter_candidates((
            make_result(first),
            make_result(second),
        ))

        self.assertEqual(result.channel_count, 1)
        self.assertIn("Channel One", result.m3u_content)
        self.assertNotIn("Another Display Name", result.m3u_content)


class TestChannelIdentityDeduplication(unittest.TestCase):

    def test_tvg_id_uses_trimmed_nfc_exact_comparison(self):
        first = make_candidate(
            "https://example.com/one.ts",
            "First",
            tvg_id="café",
        )
        second = make_candidate(
            "https://example.com/two.ts",
            "Second",
            tvg_id="cafe\u0301",
            item_order=2,
        )

        result = iptv_filter.filter_candidates((
            make_result(first),
            make_result(second),
        ))

        self.assertEqual(result.channel_count, 1)

    def test_tvg_id_comparison_is_case_sensitive(self):
        lower = make_candidate(
            "https://example.com/lower.ts",
            "Lower",
            tvg_id="channel",
        )
        upper = make_candidate(
            "https://example.com/upper.ts",
            "Upper",
            tvg_id="CHANNEL",
            item_order=2,
        )

        result = iptv_filter.filter_candidates((
            make_result(lower),
            make_result(upper),
        ))

        self.assertEqual(result.channel_count, 2)

    def test_name_and_group_use_nfkc_and_case_insensitive_match(self):
        first = make_candidate(
            "https://example.com/one.ts",
            "  Sports   Channel ",
            group_title="  Live   TV ",
        )
        second = make_candidate(
            "https://example.com/two.ts",
            "sports channel",
            group_title="live tv",
            item_order=2,
        )

        result = iptv_filter.filter_candidates((
            make_result(first),
            make_result(second),
        ))

        self.assertEqual(result.channel_count, 1)
        self.assertIn("Sports Channel", result.m3u_content)

    def test_different_groups_are_not_duplicates(self):
        first = make_candidate(
            "https://example.com/one.ts",
            "Channel",
            group_title="Sports",
        )
        second = make_candidate(
            "https://example.com/two.ts",
            "Channel",
            group_title="News",
            item_order=2,
        )

        result = iptv_filter.filter_candidates((
            make_result(first),
            make_result(second),
        ))

        self.assertEqual(result.channel_count, 2)

    def test_id_and_name_group_categories_are_not_cross_compared(self):
        with_id = make_candidate(
            "https://example.com/one.ts",
            "Channel",
            tvg_id="channel",
        )
        without_id = make_candidate(
            "https://example.com/two.ts",
            "Channel",
            item_order=2,
        )

        result = iptv_filter.filter_candidates((
            make_result(with_id),
            make_result(without_id),
        ))

        self.assertEqual(result.channel_count, 2)

    def test_empty_group_is_equivalent_to_missing_group(self):
        missing = make_candidate(
            "https://example.com/one.ts",
            "Channel",
        )
        empty = make_candidate(
            "https://example.com/two.ts",
            "Channel",
            group_title="   ",
            item_order=2,
        )

        result = iptv_filter.filter_candidates((
            make_result(missing),
            make_result(empty),
        ))

        self.assertEqual(result.channel_count, 1)


class TestM3UGeneration(unittest.TestCase):

    def test_attribute_order_and_optional_fields(self):
        candidate = make_candidate(
            "https://example.com/live.ts",
            "Channel",
            tvg_id="channel-1",
            tvg_name="Ignored TVG Name",
            group_title="Sports",
        )

        result = iptv_filter.filter_candidates((make_result(candidate),))

        self.assertEqual(result.channel_count, 1)
        self.assertEqual(
            result.m3u_content,
            '#EXTM3U\n'
            '#EXTINF:-1 tvg-id="channel-1" '
            'tvg-name="Channel" group-title="Sports",Channel\n'
            'https://example.com/live.ts\n',
        )

    def test_missing_optional_fields_are_omitted(self):
        candidate = make_candidate(
            "https://example.com/live.ts",
            "Channel",
        )

        result = iptv_filter.filter_candidates((make_result(candidate),))

        self.assertEqual(
            result.m3u_content.splitlines()[1],
            '#EXTINF:-1 tvg-name="Channel",Channel',
        )

    def test_quotes_and_line_breaks_are_cleaned(self):
        candidate = make_candidate(
            "https://example.com/live.ts",
            'News "HD"\nChannel',
            tvg_id='id"\nvalue',
            group_title='Group"\nName',
        )

        result = iptv_filter.filter_candidates((make_result(candidate),))

        self.assertEqual(result.channel_count, 1)
        self.assertIn("tvg-id=\"id' value\"", result.m3u_content)
        self.assertIn("tvg-name=\"News 'HD' Channel\"", result.m3u_content)
        self.assertIn("group-title=\"Group' Name\"", result.m3u_content)
        self.assertNotIn("\r", result.m3u_content)


if __name__ == "__main__":
    unittest.main()
