"""Tests for the shared data models and their interface contract."""

import unittest
from dataclasses import FrozenInstanceError, fields, is_dataclass
from typing import (
    Optional,
    Tuple,
    get_args,
    get_origin,
    get_type_hints,
)

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


MODEL_CLASSES = (
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


class TestModelContract(unittest.TestCase):

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
        for model_class in MODEL_CLASSES:
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

    def test_all_field_types_match_interface_contract(self):
        expected_types = {
            SourceRecord: {
                "url": str,
                "kind": SourceKind,
                "order": int,
                "name": Optional[str],
            },
            DownloadResult: {
                "source": SourceRecord,
                "success": bool,
                "content": bytes,
                "status_code": Optional[int],
                "error": Optional[str],
                "bytes_received": int,
                "truncated": bool,
            },
            IndexParseResult: {
                "index_source": SourceRecord,
                "sources": Tuple[SourceRecord, ...],
                "invalid_count": int,
                "messages": Tuple[str, ...],
            },
            Candidate: {
                "url": str,
                "name": str,
                "source_kind": SourceKind,
                "source_order": int,
                "item_order": int,
                "tvg_id": Optional[str],
                "tvg_name": Optional[str],
                "group_title": Optional[str],
                "source_url": Optional[str],
            },
            NetworkResult: {
                "success": bool,
                "requested_url": str,
                "content": bytes,
                "final_url": Optional[str],
                "remote_ip": Optional[str],
                "status_code": Optional[int],
                "content_type": Optional[str],
                "bytes_received": int,
                "redirects": Tuple[str, ...],
                "error": Optional[str],
            },
            ValidationResult: {
                "candidate": Candidate,
                "passed": bool,
                "stream_type": StreamType,
                "completed": bool,
                "reason": Optional[str],
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
                "error": Optional[str],
            },
            StageResult: {
                "stage_name": str,
                "elapsed_seconds": float,
                "success": bool,
                "incomplete": bool,
                "message": Optional[str],
            },
            RunSummary: {
                "mode": RunMode,
                "exit_code": ExitCode,
                "stage_results": Tuple[StageResult, ...],
                "sources_attempted": int,
                "candidates_collected": int,
                "candidates_validated": int,
                "candidates_passed": int,
                "candidates_incomplete": int,
                "channels_published": int,
                "incomplete": bool,
                "messages": Tuple[str, ...],
            },
        }

        for model_class, expected_fields in expected_types.items():
            actual_types = get_type_hints(model_class)

            for field_name, expected_type in expected_fields.items():
                actual_type = actual_types[field_name]

                with self.subTest(
                    model=model_class.__name__,
                    field=field_name,
                ):
                    if get_origin(expected_type) is tuple:
                        self.assertIs(get_origin(actual_type), tuple)
                        self.assertEqual(
                            get_args(actual_type),
                            get_args(expected_type),
                        )
                    else:
                        self.assertEqual(actual_type, expected_type)

    def test_all_models_are_frozen_dataclasses(self):
        for model_class in MODEL_CLASSES:
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
                    content=b"test",
                    bytes_received=4,
                    truncated=truncated,
                )

                self.assertEqual(result.success, success)
                self.assertEqual(result.truncated, truncated)

    def test_index_parse_result_defaults(self):
        result = IndexParseResult(index_source=self.sourc
