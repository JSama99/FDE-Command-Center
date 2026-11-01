"""MC-005b: deterministic chaos simulation engine tests.

Real production code (backend.chaos_simulation) only. Fixture and
receipt immutability verified by hash/dir snapshots; no mission,
receipt, snapshot, provider, or network interaction exists to test
beyond asserting the engine never touches those subsystems.
"""

import copy
import hashlib
import inspect
import unittest
from pathlib import Path

from backend import chaos_simulation as sim
from backend.chaos_simulation import (ChaosError, list_scenarios,
                                      run_simulation,
                                      validate_simulation_result)

ROOT = Path(__file__).resolve().parents[1]
CHAOS_DIR = ROOT / "fixtures" / "chaos-lab"
CASE_DIR = ROOT / "fixtures" / "case-001"
RECEIPTS_DIR = ROOT / "evaluator-private" / "receipts"
SCENARIOS = ("CHS-ASSIGN-01", "CHS-ACK-01", "CHS-WINDOW-01")


def file_hashes(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(directory).iterdir()) if p.is_file()}


class EngineBehaviorTest(unittest.TestCase):
    def test_repeatability(self):
        for sid in SCENARIOS:
            for variant in ("baseline", "injected"):
                first = run_simulation(sid, variant)
                second = run_simulation(sid, variant)
                self.assertEqual(first, second)
                self.assertEqual(
                    validate_simulation_result(first)["run"], "reproducible")

    def test_assignment_detection_and_negative_control(self):
        injected = run_simulation("CHS-ASSIGN-01", "injected")
        self.assertEqual(injected["detector"]["flagged"],
                         ["CHS-A", "CHS-B", "CHS-C"])
        self.assertTrue(injected["expected_vs_observed"]["agreement"])
        validate_simulation_result(injected)
        baseline = run_simulation("CHS-ASSIGN-01", "baseline")
        self.assertEqual(baseline["detector"]["flagged"], [])
        validate_simulation_result(baseline)
        self.assertEqual(
            baseline["observations"]["CHS-B"]["classification"],
            "confirmed-miss")

    def test_ack_feed_gap_and_negative_control(self):
        injected = run_simulation("CHS-ACK-01", "injected")
        self.assertEqual(injected["detector"]["flagged"], ["CHS-A"])
        self.assertTrue(injected["expected_vs_observed"]["agreement"])
        validate_simulation_result(injected)
        baseline = run_simulation("CHS-ACK-01", "baseline")
        self.assertEqual(baseline["detector"]["flagged"], [])
        validate_simulation_result(baseline)

    def test_window_classification_and_negative_control(self):
        injected = run_simulation("CHS-WINDOW-01", "injected")
        self.assertEqual(injected["detector"]["flagged"],
                         ["CHS-W1", "CHS-W2"])
        for case in ("CHS-W1", "CHS-W2"):
            self.assertEqual(
                injected["observations"][case]["classification"],
                "incomplete")
        validate_simulation_result(injected)
        baseline = run_simulation("CHS-WINDOW-01", "baseline")
        self.assertTrue(baseline["observations"]["CHS-W2"]["window_complete"])
        self.assertNotIn("CHS-W2", baseline["detector"]["flagged"])
        validate_simulation_result(baseline)

    def test_recovery_never_verified(self):
        for sid in SCENARIOS:
            for variant in ("baseline", "injected"):
                result = run_simulation(sid, variant)
                self.assertEqual(result["recovery"], "not-tested")
        tampered = run_simulation("CHS-ACK-01", "injected")
        tampered["recovery"] = "verified"
        with self.assertRaises(ChaosError):
            validate_simulation_result(tampered)

    def test_source_refs_and_expected_reporting(self):
        for sid in SCENARIOS:
            result = run_simulation(sid, "injected")
            for ref in result["refs"]:
                self.assertTrue((ROOT / ref).is_file(), msg=ref)
            evo = result["expected_vs_observed"]
            self.assertIn("injected_truth", evo)
            self.assertIn("detector_output", evo)
            self.assertIn("not independent discovery", evo["note"])
            self.assertTrue(evo["agreement"])


class IsolationTest(unittest.TestCase):
    def test_fixture_immutability(self):
        before = file_hashes(CHAOS_DIR)
        for sid in SCENARIOS:
            for variant in ("baseline", "injected"):
                validate_simulation_result(run_simulation(sid, variant))
        self.assertEqual(file_hashes(CHAOS_DIR), before)
        self.assertEqual(sorted(before),
                         ["ack_feed.csv", "ack_source.csv", "assign.csv",
                          "window.csv"])

    def test_case_evidence_and_receipts_untouched(self):
        case_before = file_hashes(CASE_DIR)
        receipts_before = file_hashes(RECEIPTS_DIR)
        for sid in SCENARIOS:
            for variant in ("baseline", "injected"):
                run_simulation(sid, variant)
        self.assertEqual(file_hashes(CASE_DIR), case_before)
        self.assertEqual(file_hashes(RECEIPTS_DIR), receipts_before)

    def test_engine_takes_no_mission_state(self):
        for name in ("run_simulation", "validate_simulation_result",
                     "list_scenarios"):
            params = inspect.signature(getattr(sim, name)).parameters
            for banned in ("ctx", "context", "mission", "experiment"):
                self.assertNotIn(banned, params)

    def test_no_withheld_or_provider_dependencies(self):
        import re

        source = Path(sim.__file__).read_text()
        for token in ("SRC-FEED", "09:40", "MODEL_API_KEY", "meta_adapter",
                      "model_client", "from .", "from backend",
                      "import backend"):
            self.assertNotIn(token, source, msg=token)
        for pattern in (r"^\s*import\s+(subprocess|socket|urllib|http|ssl)\b",
                        r"^\s*from\s+(subprocess|socket|urllib|http|ssl)\b",
                        r"\bos\.(system|popen|exec)",
                        r"subprocess\.\w+\("):
            self.assertIsNone(re.search(pattern, source, re.MULTILINE),
                              msg=pattern)

    def test_invalid_scenario_and_variant_rejected(self):
        with self.assertRaises(ChaosError) as cm:
            run_simulation("CHS-NOPE-99", "injected")
        self.assertEqual(cm.exception.code, "unknown-scenario")
        with self.assertRaises(ChaosError) as cm:
            run_simulation("CHS-ACK-01", "chaos")
        self.assertEqual(cm.exception.code, "unknown-variant")

    def test_malformed_results_rejected(self):
        good = run_simulation("CHS-ACK-01", "injected")
        cases = {
            "bad-schema": {"schema": "ChaosResultV9"},
            "unknown-scenario": {"scenario_id": "CHS-NOPE-99"},
            "run-mismatch": {"run_id": "0" * 64},
            "bad-classification": {"classification": "field evidence"},
            "bad-status": {"status": "passed"},
        }
        for code, mutation in cases.items():
            tampered = copy.deepcopy(good)
            tampered.update(mutation)
            with self.assertRaises(ChaosError, msg=code):
                validate_simulation_result(tampered)

    def test_fabricated_flag_rejected(self):
        tampered = run_simulation("CHS-ACK-01", "baseline")
        tampered["detector"] = dict(tampered["detector"],
                                   flagged=["CHS-B"], basis=["CHS-B"])
        with self.assertRaises(ChaosError) as cm:
            validate_simulation_result(tampered)
        self.assertEqual(cm.exception.code, "unsupported-flag")

    def test_scenarios_listed(self):
        listed = {s["scenario_id"] for s in list_scenarios()}
        self.assertEqual(listed, set(SCENARIOS))


if __name__ == "__main__":
    unittest.main()
