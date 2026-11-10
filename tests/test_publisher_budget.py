
"""Tests for the shared publication stage deadline."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import publisher
from models import ExitCode, FilterResult, RunMode


VALID_M3U = (
    "#EXTM3U\n"
    '#EXTINF:-1 tvg-name="Test Channel",Test Channel\n'
    "https://example.com/live.ts\n"
)


class TestPublisherBudget(unittest.TestCase):

    def test_expired_atomic_write_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "iptv.m3u"
            target.write_text("OLD FILE\n", encoding="utf-8")

            with self.assertRaises(publisher.PublishError):
                publisher._atomic_write(
                    target,
                    VALID_M3U,
                    deadline=time.monotonic() - 1,
                )

            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "OLD FILE\n",
            )

    def test_expired_git_deadline_stops_before_git_commands(self):
        with patch.object(publisher, "_git") as git:
            with self.assertRaises(publisher.GitPublishError):
                publisher._publish_git(
                    Path("."),
                    "output/iptv.m3u",
                    deadline=time.monotonic() - 1,
                )

            git.assert_not_called()

    def test_publish_uses_one_deadline_for_file_and_git(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original_atomic_write = publisher._atomic_write

            def atomic_write_with_deadline(target, content, deadline=None):
                self.assertIsNotNone(deadline)
                return original_atomic_write(target, content, deadline)

            with patch.object(
                publisher.config,
                "FORMAL_OUTPUT_PATH",
                "output/iptv.m3u",
            ), patch.object(
                publisher.config,
                "PUBLISH_BUDGET_SECONDS",
                30,
            ), patch.object(
                publisher,
                "_git_text",
                return_value=str(root),
            ), patch.object(
                publisher,
                "_atomic_write",
                side_effect=atomic_write_with_deadline,
            ), patch.object(
                publisher,
                "_publish_git",
                return_value=(True, True),
            ) as git_publish:
                result = publisher.publish(
                    FilterResult(VALID_M3U, 1),
                    RunMode.FORMAL,
                    repository_root=root,
                )

            self.assertTrue(result.success)
            self.assertEqual(result.exit_code, ExitCode.SUCCESS)

            git_deadline = git_publish.call_args.kwargs["deadline"]
            self.assertIsInstance(git_deadline, float)

    def test_zero_budget_fails_before_creating_test_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            with patch.object(
                publisher.config,
                "TEST_OUTPUT_PATH",
                "output/test/iptv-test.m3u",
            ), patch.object(
                publisher.config,
                "PUBLISH_BUDGET_SECONDS",
                0,
            ):
                result = publisher.publish(
                    FilterResult(VALID_M3U, 1),
                    RunMode.TEST,
                    repository_root=root,
                )

            self.assertFalse(result.success)
            self.assertEqual(result.exit_code, ExitCode.PUBLISH_ERROR)
            self.assertFalse(
                (root / "output" / "test" / "iptv-test.m3u").exists()
            )


if __name__ == "__main__":
    unittest.main()
