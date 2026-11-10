
"""Business tests for safe IPTV publication."""

import os
import subprocess
import tempfile
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

SECOND_M3U = (
    "#EXTM3U\n"
    '#EXTINF:-1 tvg-name="New Channel",New Channel\n'
    "https://example.com/new.ts\n"
)


def make_result(content=VALID_M3U, count=1):
    return FilterResult(
        m3u_content=content,
        channel_count=count,
    )


def completed(args, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=args,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class TestM3UValidation(unittest.TestCase):

    def test_accepts_valid_m3u(self):
        self.assertEqual(publisher._validate_m3u(VALID_M3U), 1)

    def test_rejects_empty_content(self):
        with self.assertRaises(publisher.PublishError):
            publisher._validate_m3u("")

    def test_rejects_bom(self):
        with self.assertRaises(publisher.PublishError):
            publisher._validate_m3u("\ufeff" + VALID_M3U)

    def test_rejects_crlf(self):
        with self.assertRaises(publisher.PublishError):
            publisher._validate_m3u(
                VALID_M3U.replace("\n", "\r\n")
            )

    def test_rejects_missing_final_lf(self):
        with self.assertRaises(publisher.PublishError):
            publisher._validate_m3u(VALID_M3U.rstrip("\n"))

    def test_rejects_wrong_header(self):
        with self.assertRaises(publisher.PublishError):
            publisher._validate_m3u(
                VALID_M3U.replace("#EXTM3U", "#INVALID", 1)
            )

    def test_rejects_missing_extinf(self):
        content = "#EXTM3U\nhttps://example.com/live.ts\n"

        with self.assertRaises(publisher.PublishError):
            publisher._validate_m3u(content)

    def test_rejects_empty_channel_name(self):
        content = (
            "#EXTM3U\n"
            "#EXTINF:-1,\n"
            "https://example.com/live.ts\n"
        )

        with self.assertRaises(publisher.PublishError):
            publisher._validate_m3u(content)

    def test_rejects_missing_channel_url(self):
        content = (
            "#EXTM3U\n"
            '#EXTINF:-1 tvg-name="Channel",Channel\n'
        )

        with self.assertRaises(publisher.PublishError):
            publisher._validate_m3u(content)

    def test_rejects_invalid_url(self):
        content = (
            "#EXTM3U\n"
            '#EXTINF:-1 tvg-name="Channel",Channel\n'
            "/relative/live.ts\n"
        )

        with self.assertRaises(publisher.PublishError):
            publisher._validate_m3u(content)

    def test_rejects_zero_channels(self):
        with self.assertRaises(publisher.PublishError):
            publisher._validate_m3u("#EXTM3U\n")

    def test_rejects_invalid_utf8(self):
        with self.assertRaises(publisher.PublishError):
            publisher._validate_bytes(b"\xff\xfe")


class TestAtomicWrite(unittest.TestCase):

    def test_writes_valid_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "iptv.m3u"

            publisher._atomic_write(target, VALID_M3U)

            self.assertTrue(target.exists())
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                VALID_M3U,
            )

    def test_invalid_content_does_not_replace_old_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "iptv.m3u"
            target.write_text("OLD CONTENT\n", encoding="utf-8")

            with self.assertRaises(publisher.PublishError):
                publisher._atomic_write(target, "#INVALID\n")

            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "OLD CONTENT\n",
            )

    def test_failed_write_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "iptv.m3u"

            with self.assertRaises(publisher.PublishError):
                publisher._atomic_write(target, "#INVALID\n")

            self.assertFalse(target.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])


class TestPublishInputValidation(unittest.TestCase):

    def test_rejects_wrong_result_type(self):
        result = publisher.publish("invalid", RunMode.TEST)

        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, ExitCode.INPUT_ERROR)

    def test_rejects_wrong_mode_type(self):
        result = publisher.publish(make_result(), "test")

        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, ExitCode.INPUT_ERROR)

    def test_rejects_boolean_channel_count(self):
        result = publisher.publish(
            FilterResult(VALID_M3U, True),
            RunMode.TEST,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, ExitCode.INPUT_ERROR)

    def test_rejects_negative_channel_count(self):
        result = publisher.publish(
            FilterResult(VALID_M3U, -1),
            RunMode.TEST,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, ExitCode.INPUT_ERROR)

    def test_rejects_channel_count_mismatch(self):
        result = publisher.publish(
            make_result(VALID_M3U, 2),
            RunMode.TEST,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, ExitCode.PUBLISH_ERROR)


class TestTestModeIsolation(unittest.TestCase):

    def test_test_mode_writes_only_test_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal = root / "output" / "iptv.m3u"
            test_file = root / "output" / "test" / "iptv-test.m3u"

            formal.parent.mkdir(parents=True)
            formal.write_text("FORMAL OLD FILE\n", encoding="utf-8")

            with patch.object(
                publisher.config,
                "FORMAL_OUTPUT_PATH",
                "output/iptv.m3u",
            ), patch.object(
                publisher.config,
                "TEST_OUTPUT_PATH",
                "output/test/iptv-test.m3u",
            ), patch.object(
                publisher,
                "_publish_git",
            ) as git_publish:
                result = publisher.publish(
                    make_result(),
                    RunMode.TEST,
                    repository_root=root,
                )

            self.assertTrue(result.success)
            self.assertEqual(result.exit_code, ExitCode.SUCCESS)
            self.assertEqual(
                result.target_path,
                "output/test/iptv-test.m3u",
            )
            self.assertFalse(result.git_pushed)
            self.assertFalse(result.remote_verified)
            self.assertEqual(
                formal.read_text(encoding="utf-8"),
                "FORMAL OLD FILE\n",
            )
            self.assertEqual(
                test_file.read_text(encoding="utf-8"),
                VALID_M3U,
            )
            git_publish.assert_not_called()

    def test_test_mode_rejects_zero_channels(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                publisher.config,
                "TEST_OUTPUT_PATH",
                "output/test/iptv-test.m3u",
            ):
                result = publisher.publish(
                    make_result("#EXTM3U\n", 0),
                    RunMode.TEST,
                    repository_root=Path(directory),
                )

            self.assertFalse(result.success)
            self.assertEqual(result.exit_code, ExitCode.PUBLISH_ERROR)

    def test_test_mode_preserves_old_file_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "output" / "test" / "iptv-test.m3u"
            target.parent.mkdir(parents=True)
            target.write_text("OLD TEST FILE\n", encoding="utf-8")

            with patch.object(
                publisher.config,
                "TEST_OUTPUT_PATH",
                "output/test/iptv-test.m3u",
            ):
                result = publisher.publish(
                    make_result("#INVALID\n", 1),
                    RunMode.TEST,
                    repository_root=root,
                )

            self.assertFalse(result.success)
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "OLD TEST FILE\n",
            )

    def test_rejects_path_outside_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                publisher.config,
                "TEST_OUTPUT_PATH",
                "../outside.m3u",
            ):
                result = publisher.publish(
                    make_result(),
                    RunMode.TEST,
                    repository_root=Path(directory),
                )

            self.assertFalse(result.success)
            self.assertEqual(result.exit_code, ExitCode.PUBLISH_ERROR)


class TestFormalPublishProtection(unittest.TestCase):

    def test_damaged_old_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "output" / "iptv.m3u"
            target.parent.mkdir(parents=True)
            target.write_text("DAMAGED OLD FILE\n", encoding="utf-8")

            with patch.object(
                publisher.config,
                "FORMAL_OUTPUT_PATH",
                "output/iptv.m3u",
            ), patch.object(
                publisher,
                "_git_text",
                return_value=str(root),
            ), patch.object(
                publisher,
                "_publish_git",
            ) as git_publish:
                result = publisher.publish(
                    make_result(),
                    RunMode.FORMAL,
                    repository_root=root,
                )

            self.assertFalse(result.success)
            self.assertEqual(result.exit_code, ExitCode.PUBLISH_ERROR)
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "DAMAGED OLD FILE\n",
            )
            git_publish.assert_not_called()

    def test_valid_old_file_can_be_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "output" / "iptv.m3u"
            target.parent.mkdir(parents=True)
            target.write_text(VALID_M3U, encoding="utf-8")

            with patch.object(
                publisher.config,
                "FORMAL_OUTPUT_PATH",
                "output/iptv.m3u",
            ), patch.object(
                publisher,
                "_git_text",
                return_value=str(root),
            ), patch.object(
                publisher,
                "_publish_git",
                return_value=(True, True),
            ) as git_publish:
                result = publisher.publish(
                    make_result(SECOND_M3U),
                    RunMode.FORMAL,
                    repository_root=root,
                )

            self.assertTrue(result.success)
            self.assertEqual(result.exit_code, ExitCode.SUCCESS)
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                SECOND_M3U,
            )
            self.assertTrue(result.git_pushed)
            self.assertTrue(result.remote_verified)
            git_publish.assert_called_once()

    def test_first_formal_publish_can_create_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "output" / "iptv.m3u"

            with patch.object(
                publisher.config,
                "FORMAL_OUTPUT_PATH",
                "output/iptv.m3u",
            ), patch.object(
                publisher,
                "_git_text",
                return_value=str(root),
            ), patch.object(
                publisher,
                "_publish_git",
                return_value=(True, True),
            ):
                result = publisher.publish(
                    make_result(),
                    RunMode.FORMAL,
                    repository_root=root,
                )

            self.assertTrue(result.success)
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                VALID_M3U,
            )


class TestGitPublication(unittest.TestCase):

    def run_git_publish(self, remote_sha=None, dirty=False,
                        remote_error=False):
        expected_sha = "a" * 40
        commands = []

        def fake_git(root, args, timeout):
            commands.append(list(args))

            if args[:2] == ["check-ref-format", "--branch"]:
                return completed(args)

            if args[:2] == ["status", "--porcelain"]:
                status = " M output/iptv.m3u\n" if dirty else ""
                return completed(args, stdout=status)

            if args[0] in ("add", "commit", "push"):
                return completed(args)

            if args[0] == "rev-parse":
                return completed(args, stdout=expected_sha + "\n")

            if args[0] == "ls-remote":
                if remote_error:
                    return completed(
                        args,
                        returncode=1,
                        stderr="Remote unavailable",
                    )

                value = remote_sha or expected_sha
                return completed(
                    args,
                    stdout=f"{value}\trefs/heads/main\n",
                )

            raise AssertionError(f"Unexpected Git command: {args}")

        with patch.dict(os.environ, {"GITHUB_REF_NAME": "main"}), patch.object(
            publisher,
            "_git",
            side_effect=fake_git,
        ):
            result = publisher._publish_git(
                Path("."),
                "output/iptv.m3u",
            )

        return result, commands

    def test_matching_remote_sha_is_success(self):
        result, _ = self.run_git_publish()

        self.assertEqual(result, (True, True))

    def test_only_formal_output_is_staged_and_committed(self):
        result, commands = self.run_git_publish(dirty=True)

        self.assertEqual(result, (True, True))
        self.assertIn(
            ["add", "--", "output/iptv.m3u"],
            commands,
        )

        commit_command = next(
            item for item in commands
            if item[0] == "commit"
        )
        self.assertIn("--only", commit_command)
        self.assertEqual(commit_command[-1], "output/iptv.m3u")

    def test_remote_sha_mismatch_is_failure(self):
        with self.assertRaises(publisher.GitPublishError):
            self.run_git_publish(remote_sha="b" * 40)

    def test_remote_sha_unavailable_is_unconfirmed(self):
        with self.assertRaises(publisher.GitPublishUnconfirmed):
            self.run_git_publish(remote_error=True)


if __name__ == "__main__":
    unittest.main()
