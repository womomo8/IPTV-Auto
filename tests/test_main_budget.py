
"""Tests for the pipeline's configured runtime budgets."""

import unittest

import config


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


if __name__ == "__main__":
    unittest.main()
