
"""Tests for pipeline runtime budgets and cleanup timing."""

import unittest
from unittest.mock import patch

import config
import main
from models import ExitCode, RunMode, StageResult


class TestPipelineBudgetConfiguration(unittest.TestCase):

    def test_stage_budgets_match_master_plan(self):
        expected = {
            "COLLECTION_BUDGET_SECONDS": 180,
            "NORMALIZATION_BUDGET_SECONDS": 30,
            "DETECTION_BUDGET_SECONDS": 660,
            "FILTER_BUDGET_SECONDS": 30,
            "PUBLISH_BUDGET_SECONDS": 120,
            "CLEANUP_BUDGET_SECONDS": 60,
        }

        for name, value in expected.items():
            with self.subTest(setting=name):
                self.assertEqual(getattr(config, name), value)

    def test_stage_budget_total_is_18_minutes(self):
        actual_total = (
            config.COLLECTION_BUDGET_SECONDS
            + config.NORMALIZATION_BUDGET_SECONDS
            + config.DETECTION_BUDGET_SECONDS
            + config.FILTER_BUDGET_SECONDS
            + config.PUBLISH_BUDGET_SECONDS
            + config.CLEANUP_BUDGET_SECONDS
        )

        self.assertEqual(actual_total, 18 * 60)
        self.assertEqual(
            config.STAGE_BUDGET_TOTAL_SECONDS,
            actual_total,
        )

    def test_startup_reserve_is_one_minute(self):
        self.assertEqual(
            config.STARTUP_RESERVE_SECONDS,
            60,
        )

    def test_normal_run_target_is_19_minutes(self):
        self.assertEqual(
            config.NORMAL_RUN_TARGET_SECONDS,
            config.STAGE_BUDGET_TOTAL_SECONDS
            + config.STARTUP_RESERVE_SECONDS,
        )
        self.assertEqual(
            config.NORMAL_RUN_TARGET_SECONDS,
            19 * 60,
        )

    def test_actions_hard_timeout_is_22_minutes(self):
        self.assertEqual(
            config.GITHUB_ACTIONS_TIMEOUT_MINUTES,
            22,
        )


class TestCleanupStageTiming(unittest.TestCase):

    def test_finish_records_actual_cleanup_duration(self):
        with (
            patch.object(main, "_log_summary") as log_summary,
            patch.object(main.time, "monotonic", return_value=12.5),
        ):
            result = main._finish(
                RunMode.TEST,
                ExitCode.SUCCESS,
                (),
                cleanup_started=10.0,
            )

        self.assertEqual(result, int(ExitCode.SUCCESS))

        summary = log_summary.call_args.args[0]
        cleanup_stages = [
            stage
            for stage in summary.stage_results
            if stage.stage_name == "收尾"
        ]

        self.assertEqual(len(cleanup_stages), 1)
        self.assertEqual(
            cleanup_stages[0].elapsed_seconds,
            2.5,
        )

    def test_finish_updates_existing_cleanup_stage(self):
        existing_stages = (
            StageResult(
                stage_name="采集",
                elapsed_seconds=1.0,
                success=True,
            ),
            StageResult(
                stage_name="收尾",
                elapsed_seconds=0.0,
                success=True,
            ),
        )

        with (
            patch.object(main, "_log_summary") as log_summary,
            patch.object(main.time, "monotonic", return_value=15.0),
        ):
            main._finish(
                RunMode.TEST,
                ExitCode.SUCCESS,
                existing_stages,
                cleanup_started=12.0,
            )

        summary = log_summary.call_args.args[0]
        cleanup_stages = [
            stage
            for stage in summary.stage_results
            if stage.stage_name == "收尾"
        ]

        self.assertEqual(len(cleanup_stages), 1)
        self.assertEqual(
            cleanup_stages[0].elapsed_seconds,
            3.0,
        )


if __name__ == "__main__":
    unittest.main()
