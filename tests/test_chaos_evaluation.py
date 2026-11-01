"""MC-005e: independent chaos evaluation tests.

Offline only: real backend.chaos_evaluation against the real engine.
No network, no provider, no writes beyond temp-free reads.
"""

import hashlib
import unittest
from pathlib import Path

from backend import chaos_evaluation as ev
from backend.chaos_evaluation import (ORACLE, compute_metrics, evaluate,
                                      evaluate_case)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "fixtures" / "chaos-lab"
CASE_DIR = ROOT / "fixtures" / "case-001"
RECEIPTS_DIR = ROOT / "evaluator-private" / "receipts"


def hashes(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(directory).iterdir()) if p.is_file()}


class OracleIndependenceTest(unittest.TestCase):
    def test_oracle_labels_are_hand_specified(self):
        # The oracle's expectations are literals in the module: the same
        # six binary judgments, written out independently here. Any drift
        # between these literals and the module means the oracle changed.
        expected = {
            ("CHS-ASSIGN-01", "injected"): ["CHS-A", "CHS-B", "CHS-C"],
            ("CHS-ASSIGN-01", "baseline"): [],
            ("CHS-ACK-01", "injected"): ["CHS-A"],
            ("CHS-ACK-01", "baseline"): [],
            ("CHS-WINDOW-01", "injected"): ["CHS-W1", "CHS-W2"],
            ("CHS-WINDOW-01", "baseline"): ["CHS-W1"],
        }
        for key, flags in expected.items():
            self.assertIn(key, ORACLE)
            self.assertEqual(ORACLE[key]["expected_flags"], flags)
            self.assertEqual(ORACLE[key]["kind"],
                             "safety" if key[0] == "CHS-WINDOW-01" else "binary")

    def test_oracle_imports_no_detector_internals(self):
        import re

        import backend.chaos_evaluation as module

        source = Path(module.__file__).read_text()
        imports = set()
        for match in re.finditer(
                r"from \.chaos_simulation import \(([^)]*)\)", source):
            imports.update(n.strip() for n in match.group(1).split(","))
        self.assertEqual(imports, {"ChaosError", "fixture_bytes",
                                   "run_simulation",
                                   "validate_simulation_result"})
        self.assertNotIn("_measure_assign", source)
        self.assertNotIn("_EXPECTED_FLAGS", source)


class MetricsTest(unittest.TestCase):
    def test_full_report_confusion(self):
        report = evaluate()
        self.assertEqual(report["overall"], "pass")
        self.assertEqual(report["confusion"],
                         {"true_positives": 2, "false_positives": 0,
                          "true_negatives": 2, "false_negatives": 0})
        metrics = report["metrics"]
        self.assertEqual(metrics["precision"], 1.0)
        self.assertEqual(metrics["recall"], 1.0)
        self.assertEqual(metrics["false_positive_rate"], 0.0)
        self.assertEqual(metrics["false_negative_rate"], 0.0)
        self.assertEqual((metrics["precision_denominator"],
                          metrics["recall_denominator"],
                          metrics["false_positive_rate_denominator"],
                          metrics["false_negative_rate_denominator"]),
                         (2, 2, 2, 2))

    def test_zero_denominators_are_undefined(self):
        metrics = compute_metrics(0, 0, 0, 0)
        for key in ("precision", "recall", "false_positive_rate",
                    "false_negative_rate"):
            self.assertIsNone(metrics[key])
        partial = compute_metrics(0, 1, 1, 0)
        self.assertEqual(partial["precision"], 0.0)
        self.assertIsNone(partial["recall"])

    def test_incomplete_excluded_from_binary(self):
        report = evaluate()
        binary_cases = [j["case"] for j in report["judgments"]
                        if j.get("kind") == "binary"]
        self.assertEqual(len(binary_cases), 4)
        self.assertTrue(all("WINDOW" not in case for case in binary_cases))
        self.assertEqual(report["safety"], {"cases": 2, "correct": 2})


class AttributionAndRobustnessTest(unittest.TestCase):
    def test_preexisting_violation_attributed(self):
        report = evaluate()
        self.assertEqual(report["attribution"], "pass")
        judgment = next(j for j in report["judgments"]
                        if j["case"] == "C3-preexisting-violation")
        self.assertEqual(judgment["rule"], "R-PREEXISTING")

    def test_robustness_cases_pass(self):
        report = evaluate()
        self.assertEqual(report["robustness"],
                         {"C9-malformed-record": "pass",
                          "C10-fabricated-flag": "pass"})

    def test_unavailable_case_documented(self):
        report = evaluate()
        self.assertEqual(len(report["unavailable"]), 1)
        self.assertEqual(report["unavailable"][0]["case"], "C8-order-anomaly")
        self.assertEqual(report["indeterminate"], 0)

    def test_source_reference_integrity(self):
        report = evaluate()
        checked = 0
        for judgment in report["judgments"]:
            for ref in judgment.get("refs", []):
                self.assertTrue((ROOT / ref).is_file(), msg=ref)
                checked += 1
        self.assertGreater(checked, 0)

    def test_unknown_scenario_yields_error_not_crash(self):
        judgment = evaluate_case("CHS-NOPE-99", "injected")
        self.assertEqual(judgment["status"], "error")


class EvaluationHygieneTest(unittest.TestCase):
    def test_deterministic_reproducibility(self):
        self.assertEqual(evaluate(), evaluate())

    def test_fixture_immutability(self):
        before = hashes(FIXTURES_DIR)
        evaluate()
        self.assertEqual(hashes(FIXTURES_DIR), before)

    def test_no_side_effects(self):
        case_before = hashes(CASE_DIR)
        receipts_before = hashes(RECEIPTS_DIR)
        evaluate()
        self.assertEqual(hashes(CASE_DIR), case_before)
        self.assertEqual(hashes(RECEIPTS_DIR), receipts_before)

    def test_no_evaluation_route_exposed(self):
        from backend.server import handle_request, new_context

        for method, target in (("GET", "/api/chaos/eval"),
                               ("POST", "/api/chaos/eval"),
                               ("GET", "/api/chaos/evaluation")):
            status, _, _ = handle_request(method, target, None,
                                          new_context())
            self.assertEqual(status, 404, msg=f"{method} {target}")

    def test_report_scope_limitation(self):
        report = evaluate()
        self.assertIn("does not establish production reliability",
                      report["scope"])
        self.assertEqual(report["schema"], "ChaosEvaluationReportV1")
        self.assertEqual(report["engine_schema"], "ChaosSimulationResultV1")


if __name__ == "__main__":
    unittest.main()
