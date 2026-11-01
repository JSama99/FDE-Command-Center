"""Task 009.7g: offline end-to-end acceptance of the strengthened contract.

One mock invocation flows through instructions, validation, receipt, and
verification. No network, no credentials, no intermediate files.
"""

import hashlib
import json
import unittest
from pathlib import Path
from unittest import mock

from backend.investigation import DiagnosticError, produce_investigation
from backend.meta_adapter import MockAdapter
from backend.receipt import (produce_investigation_with_receipt,
                             review_text, verify_receipt)
from tests.test_task004 import valid_payload

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_ID = "1902c485a31f4e45"
HISTORICAL_DIR = ROOT / "evaluator-private" / "receipts" / HISTORICAL_ID


def compliant_investigation():
    """Three hypotheses, linked discriminating experiments, one
    source-quality check, approval-gated recommendation, no causal claims."""
    payload = valid_payload()
    payload["competing_hypotheses"] = [
        {"text": "Queue-handling delays leave urgent cases unassigned.",
         "refs": ["dispatcher", "events.csv"], "status": "hypothesis"},
        {"text": "An acknowledgment feed gap loses timely entries.",
         "refs": ["events.csv", "case-003"], "status": "hypothesis"},
        {"text": "Dashboard counts misstate acknowledgment state.",
         "refs": ["events.csv"], "status": "hypothesis"},
    ]
    payload["diagnostic_experiments"] = [
        {"text": "Audit overnight assignment coverage against the queue log.",
         "refs": ["dispatcher", "events.csv"],
         "question": "Does queue handling explain the unassigned cases?",
         "outcomes": {"supports": "Coverage gaps match unassigned cases.",
                      "weakens": "Coverage is complete despite gaps."},
         "tests": [0]},
        {"text": "Reconcile the case-003 source log against the events feed.",
         "refs": ["events.csv", "case-003"],
         "question": "Does the feed lose acknowledgments the source holds?",
         "outcomes": {"supports": "Source entries are missing from the feed.",
                      "weakens": "Feed and source agree row for row."},
         "tests": [1]},
        {"text": "Recompute dashboard counts from raw event rows.",
         "refs": ["events.csv"],
         "question": "Do dashboard counts match a raw recomputation?",
         "outcomes": {"supports": "Recomputation matches the dashboard.",
                      "weakens": "Recomputation diverges from the dashboard."},
         "tests": [2]},
        {"text": "Re-verify policy quotation offsets.",
         "refs": ["policy"],
         "question": "Are the cited offsets exact?",
         "outcomes": {"supports": "Offsets verify character-exact.",
                      "weakens": "An offset mismatch is found."},
         "scope": "source-quality"},
    ]
    return payload


def json_inventory():
    return {str(p) for p in ROOT.rglob("*.json")}


class EndToEndAcceptanceTest(unittest.TestCase):
    def test_full_workflow(self):
        import tempfile
        import shutil

        before_files = json_inventory()
        historical_before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in sorted(HISTORICAL_DIR.iterdir())
                             if p.is_file()}
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)

        adapter = MockAdapter(compliant_investigation())
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network used")):
            # 1-3: instructions delivered, single invocation.
            outcome = produce_investigation_with_receipt(
                adapter, receipts_dir=Path(tmp) / "r")
        # 1: adapter received the updated instructions.
        self.assertIn("diagnostic_experiments", adapter.last_instructions)
        self.assertIn("outcomes", adapter.last_instructions)
        # 2: instructions explain coverage and discrimination.
        self.assertIn("untestable", adapter.last_instructions)
        self.assertIn("Source-quality", adapter.last_instructions)
        # 4-5: accepted and receipted.
        self.assertEqual(outcome["validation"], "accepted")
        self.assertIsNotNone(outcome["receipt_id"])
        self.assertEqual(outcome["summary"]["competing_hypotheses"], 3)
        # 6: integrity verification passes.
        findings = verify_receipt(outcome["receipt_id"],
                                  receipts_dir=Path(tmp) / "r")
        self.assertEqual(findings["checks"]["integrity"], "pass")
        self.assertEqual(findings["checks"]["schema-status"], "current")
        # 7: adjudication pending; review readable.
        text = review_text(outcome["receipt_id"],
                           receipts_dir=Path(tmp) / "r")
        self.assertIn("Adjudication status: pending", text)
        self.assertIn("Queue-handling delays", text)
        # 8: no intermediate JSON files written anywhere in the repo.
        self.assertEqual(json_inventory(), before_files)
        # 10: historical receipt byte-identical and readable.
        historical_after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in sorted(HISTORICAL_DIR.iterdir())
                            if p.is_file()}
        self.assertEqual(historical_after, historical_before)
        historical = verify_receipt(HISTORICAL_ID)
        self.assertEqual(historical["checks"]["integrity"], "pass")
        self.assertEqual(historical["checks"]["schema-status"],
                         "validator-version-drift")

    def test_old_schema_rejected(self):
        stale = compliant_investigation()
        for experiment in stale["diagnostic_experiments"]:
            for key in ("question", "outcomes", "tests", "scope"):
                experiment.pop(key, None)
        adapter = MockAdapter(stale)
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network used")):
            with self.assertRaises(DiagnosticError):
                produce_investigation_with_receipt(
                    adapter, receipts_dir=Path("/nonexistent-dir-0097g"))


class NegativeControlsTest(unittest.TestCase):
    def check_rejected(self, mutate, category):
        from backend.investigation import (build_evidence_registry,
                                           validate_investigation)
        from backend.report import build_case_report

        payload = compliant_investigation()
        mutate(payload)
        registry = build_evidence_registry(build_case_report(ROOT))
        with self.assertRaises(DiagnosticError) as ctx:
            validate_investigation(payload, registry)
        self.assertEqual(ctx.exception.category, category)

    def test_missing_outcomes(self):
        def mutate(payload):
            del payload["diagnostic_experiments"][0]["outcomes"]["weakens"]
        self.check_rejected(mutate, "experiment-undiscriminating")

    def test_unlinked_experiment(self):
        def mutate(payload):
            payload["diagnostic_experiments"][0]["tests"] = []
        self.check_rejected(mutate, "experiment-linkage")

    def test_source_quality_only_insufficient(self):
        def mutate(payload):
            for experiment in payload["diagnostic_experiments"]:
                experiment["scope"] = "source-quality"
                experiment.pop("tests", None)
        self.check_rejected(mutate, "experiment-coverage")

    def test_hypothesis_without_experiment_or_excuse(self):
        def mutate(payload):
            payload["diagnostic_experiments"] = [
                e for e in payload["diagnostic_experiments"] if 2 not in e.get("tests", [])]
        self.check_rejected(mutate, "experiment-coverage")

    def test_tested_and_untestable(self):
        def mutate(payload):
            payload["untestable"] = [{"hypothesis": 1,
                                      "reason": "No source log in evidence."}]
        self.check_rejected(mutate, "experiment-linkage")


if __name__ == "__main__":
    unittest.main()
