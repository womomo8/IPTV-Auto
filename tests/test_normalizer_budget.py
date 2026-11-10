
"""Tests for normalization stage budget enforcement."""

import unittest
from unittest.mock import patch

import normalizer
from models import DownloadResult, SourceKind, SourceRecord


class TestNormalizerBudget(unittest.TestCase):

    def test_stops_when_budget_expires_during_subscription_parsing(self):
        source = SourceRecord(
            url="https://example.com/list.m3u",
            kind=SourceKind.MANUAL_SUBSCRIPTION,
            order=1,
        )

        content = (
            "#EXTM3U\n"
            "#EXTINF:-1,Channel One\n"
            "https://example.com/one.ts\n"
            "#EXTINF:-1,Channel Two\n"
            "https://example.com/two.ts\n"
        ).encode("utf-8")

        result = DownloadResult(
            source=source,
            success=True,
            content=content,
            status_code=200,
            truncated=False,
        )

        # Deadline creation: 100 + 1 = 101.
        # The first four checks remain before the deadline.
        # The next check occurs during parsing and exceeds it.
        with patch.object(
            normalizer.time,
            "monotonic",
            side_effect=[
                100.0,  # Create deadline
                100.0,  # Initial budget check
                100.0,  # After sorting
                100.0,  # Before processing subscription
                100.0,  # First M3U line
                102.0,  # Second M3U line: expired
            ],
        ):
            with patch.object(
                normalizer.config,
                "NORMALIZATION_BUDGET_SECONDS",
                1,
            ):
                with self.assertRaisesRegex(
                    TimeoutError,
                    "Normalization stage budget exhausted",
                ):
                    normalizer.normalize_candidates(
                        (result,),
                        manual_stream_urls=(),
                    )

    def test_rejects_non_positive_normalization_budget(self):
        with patch.object(
            normalizer.config,
            "NORMALIZATION_BUDGET_SECONDS",
            0,
        ):
            with self.assertRaises(ValueError):
                normalizer.normalize_candidates(
                    (),
                    manual_stream_urls=(),
                )


if __name__ == "__main__":
    unittest.main()
