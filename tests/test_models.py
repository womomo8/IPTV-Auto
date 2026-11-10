"""Tests for the shared data models and their interface contract."""

import unittest
from dataclasses import FrozenInstanceError, fields, is_dataclass
from typing import get_type_hints

from models import (
    Candidate,
    DownloadResult,
    ExitCode,
    FilterResult,
    IndexParseResult,
    NetworkResult,
    PublishResult,
    RunMode,
    RunSummary,
    SourceKind,
    SourceRecord,
    StageResult,
    StreamType,
    ValidationResult,
)


class TestEnums(unittest.TestCase):
    def test_source_kind_values(self):
        self.assertEqual(SourceKind.MANUAL_STREAM.value, "manual_stream")
        self.assertEqual(
            SourceKind.MANUAL_SUBSCRIPTION.value,
            "manual_subscription",
        )
        self.assertEqual(SourceKind.AUTO_INDEX.value, "auto_index")
        self.assertEqual(
            SourceKind.AUTO_SUBSCRIPTION.value,
            "auto_subscription",
        )

    def test_run_mode_values(self):
        self.assertEqual(RunMode.FORMAL.value, "formal")
        self.assertEqual(RunMode.TEST.value, "test")

    def test_stream_type_values(self):
        self.assertEqual(StreamType.TS.value, "ts")
        self.assertEqual(StreamType.HLS.value, "hls")
        self.assertEqual(StreamType.UNKNOWN.value, "unknown")

    def test_exit_code_values(self):
        expected = {
            ExitCode.SUCCESS: 0,
            ExitCode.INPUT_ERROR: 1,
            ExitCode.STAGE_ERROR: 2,
            ExitCode.PUBLISH_ERROR: 3,
            ExitCode.PUBLISH_UNCONFIRMED: 4,
        }

        for code, value in expected.items():
            with self.subTest(code=code):
                self.assertEqual(int(code), value)


class TestDataModels(unittest.TestCase):
    def setUp(self):
        self.source = SourceRecord(
            url="https://example.com/live.m3u",
            kind=SourceKind.MANUAL_SUBSCRIPTION,
            order=0,
        )

        self.candidate = Candidate(
            url="https://example.com/live.ts",
            name="Test Channel",
            source_kind=SourceKind.MANUAL_STREAM,
            source_order=0,
            item_order=0,
        )

    def test_models_are_dataclasses(self):
        model_classes = (
            SourceRecord,
            DownloadResult,
            IndexParseResult,
            Candidate,
            NetworkResult,
            ValidationResult,
            FilterResult,
            PublishResult,
            StageResult,
            RunSummary,
        )

        for model_class in model_classes:
            with self.subTest(model=model_class.__name__):
                self.assertTrue(is_dataclass(model_class))

    def test_model_field_names(self):
        expected_fields = {
            SourceRecord: (
                "url", "kind", "order", "name",
            ),
            DownloadResult: (
                "source", "success", "content", "status_code",
                "error", "bytes_received", "truncated",
            ),
            IndexParseResult: (
                "index_source", "sources", "invalid_count", "messages",
            ),
            Candidate: (
                "url", "name", "source_kind", "source_order",
                "item_order", "tvg_id", "tvg_name",
                "group_title", "source_url",
            ),
            NetworkResult: (
                "success", "requested_url", "content", "final_url",
                "remote_ip", "status_code", "content_type",
                "bytes_received", "redirects", "error",
            ),
            ValidationResult: (
                "candidate", "passed", "stream_type",
                "completed", "reason",
            ),
            FilterResult: (
                "m3u_content", "channel_count",
            ),
            PublishResult: (
                "success", "exit_code", "target_path",
                "git_pushed", "remote_verified", "error",
            ),
            StageResult: (
                "stage_name", "elapsed_seconds", "success",
                "incomplete", "message",
            ),
            RunSummary: (
                "mode", "exit_code", "stage_results",
                "sources_attempted", "candidates_collected",
                "candidates_validated", "candidates_passed",
                "candidates_incomplete", "channels_published",
                "incomplete", "messages",
            ),
        }

        for model_class, expected in expected_fields.items():
            actual = tuple(
                field.name for field in fields(model_class)
            )

            with self.subTest(model=model_class.__name__):
                self.assertEqual(actual, expected)

    def test_model_field_types_are_resolvable(self):
        model_classes = (
            SourceRecord,
            DownloadResult,
            IndexParseResult,
            Candidate,
            NetworkResult,
            ValidationResult,
            FilterResult,
            PublishResult,
            StageResult,
            RunSummary,
        )

        for model_class in model_classes:
            with self.subTest(model=model_class.__name__):
                hints = get_type_hints(model_class)
                expected_names = {
                    field.name for field in fields(model_class)
                }

                self.assertEqual(set(hints), expected_names)

    def test_important_field_types(self):
        expected_types = {
            SourceRecord: {
                "url": str,
                "kind": SourceKind,
                "order": int,
            },
            DownloadResult: {
                "source": SourceRecord,
                "success": bool,
                "content": bytes,
                "bytes_received": int,
                "truncated": bool,
            },
            IndexParseResult: {
                "index_source": SourceRecord,
                "sources": tuple,
                "invalid_count": int,
                "messages": tuple,
            },
            Candidate: {
                "url": str,
                "name": str,
                "source_kind": SourceKind,
                "source_order": int,
                "item_order": int,
            },
            NetworkResult: {
                "success": bool,
                "requested_url": str,
                "content": bytes,
                "bytes_received": int,
                "redirects": tuple,
            },
            ValidationResult: {
                "candidate": Candidate,
                "passed": bool,
                "stream_type": StreamType,
                "completed": bool,
            },
            FilterResult: {
                "m3u_content": str,
                "channel_count": int,
            },
            PublishResult: {
                "success": bool,
                "exit_code": ExitCode,
                "target_path": str,
                "git_pushed": bool,
                "remote_verified": bool,
            },
            StageResult: {
                "stage_name": str,
                "elapsed_seconds": float,
                "success": bool,
                "incomplete": bool,
            },
            RunSummary: {
                "mode": RunMode,
                "exit_code": ExitCode,
                "stage_results": tuple,
                "sources_attempted": int,
                "candidates_collected": int,
                "candidates_validated": int,
                "candidates_passed": int,
                "candidates_incomplete": int,
                "channels_published": int,
                "incomplete": bool,
                "messages": tuple,
            },
        }

        for model_class, expected in expected_types.items():
            hints = get_type_hints(model_class)

            for field_name, expected_type in expected.items():
                with self.subTest(
                    model=model_class.__name__,
                    field=field_name,
                ):
                    self.assertIs(hints[field_name], expected_type)

    def test_all_models_are_frozen_dataclasses(self):
        model_classes = (
            SourceRecord,
            DownloadResult,
            IndexParseResult,
            Candidate,
            NetworkResult,
            ValidationResult,
            FilterResult,
            PublishResult,
            StageResult,
            RunSummary,
        )

        for model_class in model_classes:
            with self.subTest(model=model_class.__name__):
                self.assertTrue(
                    model_class.__dataclass_params__.frozen
                )

    def test_source_record_defaults(self):
        self.assertIsNone(self.source.name)

    def test_download_result_defaults(self):
        result = DownloadResult(
            source=self.source,
            success=True,
        )

        self.assertEqual(result.content, b"")
        self.assertIsNone(result.status_code)
        self.assertIsNone(result.error)
        self.assertEqual(result.bytes_received, 0)
        self.assertFalse(result.truncated)

    def test_download_result_status_combinations(self):
        combinations = (
            (True, False),
            (True, True),
            (False, True),
            (False, False),
        )

        for success, truncated in combinations:
            with self.subTest(
                success=success,
                truncated=truncated,
            ):
                result = DownloadResult(
                    source=self.source,
                    success=success,
                    content=b"partial data" if truncated else b"complete",
                    bytes_received=12,
                    truncated=truncated,
                )

                self.assertEqual(result.success, success)
                self.assertEqual(result.truncated, truncated)

    def test_index_parse_result_defaults(self):
        result = IndexParseResult(index_source=self.source)

        self.assertEqual(result.sources, ())
        self.assertEqual(result.invalid_count, 0)
        self.assertEqual(result.messages, ())

    def test_candidate_defaults(self):
        self.assertIsNone(self.candidate.tvg_id)
        self.assertIsNone(self.candidate.tvg_name)
        self.assertIsNone(self.candidate.group_title)
        self.assertIsNone(self.candidate.source_url)

    def test_network_result_defaults(self):
        result = NetworkResult(
            success=True,
            requested_url="https://example.com/",
        )

        self.assertEqual(result.content, b"")
        self.assertIsNone(result.final_url)
        self.assertIsNone(result.remote_ip)
        self.assertIsNone(result.status_code)
        self.assertIsNone(result.content_type)
        self.assertEqual(result.bytes_received, 0)
        self.assertEqual(result.redirects, ())
        self.assertIsNone(result.error)

    def test_network_success_is_independent_of_http_status(self):
        result = NetworkResult(
            success=True,
            requested_url="https://example.com/",
            status_code=404,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status_code, 404)

    def test_network_success_does_not_mean_stream_validation_passed(self):
        network_result = NetworkResult(
            success=True,
            requested_url="https://example.com/live.ts",
        )

        validation_result = ValidationResult(
            candidate=self.candidate,
            passed=False,
            completed=True,
            reason="Stream content validation failed.",
        )

        self.assertTrue(network_result.success)
        self.assertFalse(validation_result.passed)

    def test_validation_result_defaults(self):
        result = ValidationResult(
            candidate=self.candidate,
            passed=True,
        )

        self.assertEqual(result.stream_type, StreamType.UNKNOWN)
        self.assertTrue(result.completed)
        self.assertIsNone(result.reason)

    def test_incomplete_validation_cannot_pass(self):
        with self.assertRaises(ValueError):
            ValidationResult(
                candidate=self.candidate,
                passed=True,
                completed=False,
            )

    def test_incomplete_validation_can_be_failed(self):
        result = ValidationResult(
            candidate=self.candidate,
            passed=False,
            completed=False,
        )

        self.assertFalse(result.passed)
        self.assertFalse(result.completed)

    def test_filter_result(self):
        result = FilterResult(
            m3u_content="#EXTM3U\n",
            channel_count=0,
        )

        self.assertEqual(result.channel_count, 0)

    def test_publish_result_defaults(self):
        result = PublishResult(
            success=True,
            exit_code=ExitCode.SUCCESS,
            target_path="output/iptv.m3u",
        )

        self.assertFalse(result.git_pushed)
        self.assertFalse(result.remote_verified)
        self.assertIsNone(result.error)

    def test_test_mode_style_publish_does_not_require_git(self):
        result = PublishResult(
            success=True,
            exit_code=ExitCode.SUCCESS,
            target_path="output/test/iptv-test.m3u",
            git_pushed=False,
            remote_verified=False,
        )

        self.assertTrue(result.success)
        self.assertFalse(result.git_pushed)
        self.assertFalse(result.remote_verified)

    def test_publish_result_can_be_pushed_but_not_verified(self):
        result = PublishResult(
            success=False,
            exit_code=ExitCode.PUBLISH_UNCONFIRMED,
            target_path="output/iptv.m3u",
            git_pushed=True,
            remote_verified=False,
        )

        self.assertTrue(result.git_pushed)
        self.assertFalse(result.remote_verified)
        self.assertEqual(
            result.exit_code,
            ExitCode.PUBLISH_UNCONFIRMED,
        )

    def test_publish_result_can_be_verified_after_push(self):
        result = PublishResult(
            success=True,
            exit_code=ExitCode.SUCCESS,
            target_path="output/iptv.m3u",
            git_pushed=True,
            remote_verified=True,
        )

        self.assertTrue(result.success)
        self.assertTrue(result.git_pushed)
        self.assertTrue(result.remote_verified)

    def test_publish_result_rejects_success_with_failure_exit_code(self):
        with self.assertRaises(ValueError):
            PublishResult(
                success=True,
                exit_code=ExitCode.PUBLISH_ERROR,
                target_path="output/iptv.m3u",
            )

    def test_publish_result_rejects_failure_with_success_exit_code(self):
        with self.assertRaises(ValueError):
            PublishResult(
                success=False,
                exit_code=ExitCode.SUCCESS,
                target_path="output/iptv.m3u",
            )

    def test_publish_result_rejects_remote_verification_without_push(self):
        with self.assertRaises(ValueError):
            PublishResult(
                success=True,
                exit_code=ExitCode.SUCCESS,
                target_path="output/iptv.m3u",
                git_pushed=False,
                remote_verified=True,
            )

    def test_publish_result_rejects_remote_verification_on_failure(self):
        with self.assertRaises(ValueError):
            PublishResult(
                success=False,
                exit_code=ExitCode.PUBLISH_UNCONFIRMED,
                target_path="output/iptv.m3u",
                git_pushed=True,
                remote_verified=True,
            )

    def test_stage_result_defaults(self):
        result = StageResult(
            stage_name="collection",
            elapsed_seconds=1.0,
            success=True,
        )

        self.assertFalse(result.incomplete)
        self.assertIsNone(result.message)

    def test_run_summary_defaults(self):
        result = RunSummary(
            mode=RunMode.TEST,
            exit_code=ExitCode.SUCCESS,
        )

        self.assertEqual(result.stage_results, ())
        self.assertEqual(result.sources_attempted, 0)
        self.assertEqual(result.candidates_collected, 0)
        self.assertEqual(result.candidates_validated, 0)
        self.assertEqual(result.candidates_passed, 0)
        self.assertEqual(result.candidates_incomplete, 0)
        self.assertEqual(result.channels_published, 0)
        self.assertFalse(result.incomplete)
        self.assertEqual(result.messages, ())

    def test_all_model_instances_are_immutable(self):
        download = DownloadResult(
            source=self.source,
            success=True,
        )
        index_result = IndexParseResult(index_source=self.source)
        network = NetworkResult(
            success=True,
            requested_url="https://example.com/",
        )
        validation = ValidationResult(
            candidate=self.candidate,
            passed=True,
        )
        filtered = FilterResult(
            m3u_content="#EXTM3U\n",
            channel_count=0,
        )
        published = PublishResult(
            success=True,
            exit_code=ExitCode.SUCCESS,
            target_path="output/iptv.m3u",
        )
        stage = StageResult(
            stage_name="collection",
            elapsed_seconds=1.0,
            success=True,
        )
        summary = RunSummary(
            mode=RunMode.TEST,
            exit_code=ExitCode.SUCCESS,
        )

        instances = (
            self.source,
            download,
            index_result,
            self.candidate,
            network,
            validation,
            filtered,
            published,
            stage,
            summary,
        )

        for instance in instances:
            first_field = fields(instance)[0]

            with self.subTest(model=type(instance).__name__):
                with self.assertRaises(FrozenInstanceError):
                    setattr(
                        instance,
                        first_field.name,
                        getattr(instance, first_field.name),
                    )


if __name__ == "__main__":
    unittest.main()
