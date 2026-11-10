
"""Tests for the shared data models and their interface contract."""

import unittest
from dataclasses import FrozenInstanceError, fields, is_dataclass

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
