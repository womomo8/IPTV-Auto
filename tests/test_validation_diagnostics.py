
"""Tests for per-candidate validation diagnostics."""

import unittest

import main
from models import Candidate, SourceKind, ValidationResult


class TestPerCandidateDiagnostics(unittest.TestCase):

    def make_result(
        self,
        *,
        name="测试频道",
        url="https://live.example.com/live.m3u8?token=secret123",
        source_url="https://source.example.com/list.m3u?key=source-secret",
        source_order=2,
        item_order=7,
        completed=True,
        passed=False,
        reason="HTTP 403",
    ):
        candidate = Candidate(
            url=url,
            name=name,
            source_kind=SourceKind.MANUAL_SUBSCRIPTION,
            source_order=source_order,
            item_order=item_order,
            source_url=source_url,
        )
        return ValidationResult(
            candidate=candidate,
            passed=passed,
            completed=completed,
            reason=reason,
        )

    def test_logs_individual_failure_details(self):
        result = self.make_result()

        with self.assertLogs("iptv.main", level="WARNING") as captured:
            main._log_validation_diagnostics((result,))

        output = "\n".join(captured.output)

        self.assertIn("候选验证明细", output)
        self.assertIn("测试频道", output)
        self.assertIn("来源序号=2", output)
        self.assertIn("候选序号=7", output)
        self.assertIn("HTTP 403", output)
        self.assertIn("live.example.com/live.m3u8", output)
        self.assertIn("source.example.com/list.m3u", output)

    def test_hides_query_parameters(self):
        result = self.make_result()

        with self.assertLogs("iptv.main", level="WARNING") as captured:
            main._log_validation_diagnostics((result,))

        output = "\n".join(captured.output)

        self.assertNotIn("secret123", output)
        self.assertNotIn("source-secret", output)
        self.assertIn("已隐藏", output)

    def test_logs_incomplete_candidate(self):
        result = self.make_result(
            completed=False,
            reason="Candidate validation budget exhausted.",
        )

        with self.assertLogs("iptv.main", level="WARNING") as captured:
            main._log_validation_diagnostics((result,))

        output = "\n".join(captured.output)

        self.assertIn("状态=未完成", output)
        self.assertIn("Candidate validation budget exhausted.", output)

    def test_does_not_log_passed_candidate_as_failure(self):
        result = self.make_result(
            passed=True,
            reason=None,
        )

        with self.assertLogs("iptv.main", level="INFO") as captured:
            main._log_validation_diagnostics((result,))

        output = "\n".join(captured.output)

        self.assertNotIn("候选验证明细", output)
        self.assertNotIn("HTTP 403", output)


if __name__ == "__main__":
    unittest.main()
