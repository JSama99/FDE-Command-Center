"""Task 009.7e: hypothesis-discriminating diagnostic experiments. Offline only."""

import unittest
from unittest import mock

from backend.investigation import DiagnosticError, validate_investigation
from backend.report import build_case_report
from backend.server import handle_request, new_context
from tests.test_task004 import valid_payload
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def registry():
    from backend.investigation import build_evidence_registry

    return build_evidence_registry(build_case_report(ROOT))


def experiment(**over):
    item = {"text": "Check the feed.", "refs": ["events.csv"],
            "question": "Does the feed match the source log?",
            "outcomes": {"supports": "Rows match.", "weakens": "Rows diverge."},
            "tests": [0]}
    item.update(over)
    return item


def hypotheses():
    return [
        {"text": "Queue-handling delays leave urgent cases unassigned.",
         "refs": ["dispatcher", "events.csv"], "status": "hypothesis"},
        {"text": "Dashboard accuracy gap misreports acknowledgment state.",
         "refs": ["events.csv", "case-003"], "status": "hypothesis"},
    ]


def payload_with(hyps, experiments, untestable=None):
    payload = valid_payload()
    payload["competing_hypotheses"] = hyps
    payload["diagnostic_experiments"] = experiments
    if untestable is not None:
        payload["untestable"] = untestable
    elif "untestable" in payload:
        del payload["untestable"]
    return payload


class CoverageTest(unittest.TestCase):
    def test_two_source_quality_checks_do_not_cover_hypotheses(self):
        payload = payload_with(hypotheses(), [
            experiment(scope="source-quality", text="Re-verify quote offsets.",
                       refs=["policy"]),
            experiment(scope="source-quality", text="Confirm feed row counts.",
                       refs=["events.csv"]),
        ])
        with self.assertRaises(DiagnosticError) as ctx:
            validate_investigation(payload, registry())
        self.assertEqual(ctx.exception.category, "experiment-coverage")

    def test_operational_experiment_without_links_rejected(self):
        item = experiment()
        del item["tests"]
        payload = payload_with(hypotheses(), [item])
        with self.assertRaises(DiagnosticError) as ctx:
            validate_investigation(payload, registry())
        self.assertEqual(ctx.exception.category, "experiment-linkage")

    def test_out_of_range_link_rejected(self):
        payload = payload_with(hypotheses(), [experiment(tests=[7])])
        with self.assertRaises(DiagnosticError) as ctx:
            validate_investigation(payload, registry())
        self.assertEqual(ctx.exception.category, "experiment-linkage")

    def test_untestable_with_reason_accepted(self):
        payload = payload_with(
            hypotheses(),
            [experiment(tests=[0])],
            untestable=[{"hypothesis": 1,
                         "reason": "No dashboard source log exists in evidence."}])
        self.assertTrue(validate_investigation(payload, registry()))

    def test_tested_and_untestable_rejected(self):
        payload = payload_with(
            hypotheses(),
            [experiment(tests=[0, 1])],
            untestable=[{"hypothesis": 1, "reason": "No source log."}])
        with self.assertRaises(DiagnosticError) as ctx:
            validate_investigation(payload, registry())
        self.assertEqual(ctx.exception.category, "experiment-linkage")

    def test_bad_untestable_rejected(self):
        for bad in ([{"hypothesis": 5, "reason": "x"}],
                     [{"hypothesis": 0, "reason": "  "}],
                     [{"hypothesis": 0}],
                     "not-a-list"):
            payload = payload_with(hypotheses(), [experiment(tests=[0, 1])],
                                   untestable=bad)
            with self.assertRaises(DiagnosticError, msg=repr(bad)):
                validate_investigation(payload, registry())


class DiscriminationTest(unittest.TestCase):
    def test_missing_question_or_outcomes_rejected(self):
        for drop in ("question", "outcomes"):
            payload = payload_with(hypotheses(), [experiment(tests=[0, 1])])
            del payload["diagnostic_experiments"][0][drop]
            with self.assertRaises(DiagnosticError) as ctx:
                validate_investigation(payload, registry())
            self.assertEqual(ctx.exception.category, "experiment-undiscriminating",
                             msg=drop)
        payload = payload_with(hypotheses(), [experiment(
            tests=[0, 1],
            outcomes={"supports": "Rows match."})])
        with self.assertRaises(DiagnosticError) as ctx:
            validate_investigation(payload, registry())
        self.assertEqual(ctx.exception.category, "experiment-undiscriminating")

    def test_full_coverage_passes(self):
        payload = payload_with(
            hypotheses(),
            [experiment(tests=[0]),
             experiment(text="Reconcile dashboard counts.", refs=["events.csv"],
                        tests=[1])])
        self.assertTrue(validate_investigation(payload, registry()))

    def test_causal_and_evidence_rules_intact(self):
        payload = payload_with(hypotheses(),
                               [experiment(tests=[0, 1])])
        payload["competing_hypotheses"][0]["status"] = "supported finding"
        with self.assertRaises(DiagnosticError) as ctx:
            validate_investigation(payload, registry())
        self.assertEqual(ctx.exception.category, "hypothesis-status")

    def test_receipt_path_accepts_new_schema(self):
        import shutil
        import tempfile

        from backend.receipt import verify_receipt, write_receipt

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        record = write_receipt(valid_payload(), "low",
                               receipts_dir=Path(tmp) / "r")
        findings = verify_receipt(record["receipt_id"],
                                  receipts_dir=Path(tmp) / "r")
        self.assertEqual(findings["checks"]["integrity"], "pass")


if __name__ == "__main__":
    unittest.main()
