"""MC-005f: deterministic recovery verification tests.

Real production code (backend.chaos_recovery) only. Adversarial
repairs are test-local mutations passed to evaluate_repair — never
runnable via run_recovery_test. No writes, no network, no provider.
"""

import copy
import hashlib
import inspect
import unittest
from datetime import timedelta
from pathlib import Path

from backend import chaos_recovery as rec
from backend.chaos_recovery import (ChaosRecoveryError, evaluate_repair,
                                    list_recovery_scenarios, measure_assign,
                                    measure_feed, run_recovery_test,
                                    validate_recovery_result)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "fixtures" / "chaos-lab"
CASE_DIR = ROOT / "fixtures" / "case-001"
RECEIPTS_DIR = ROOT / "evaluator-private" / "receipts"


def hashes(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(directory).iterdir()) if p.is_file()}


def faulted_assign_rows():
    rows = rec._read_csv("assign.csv")
    out = []
    for row in rows:
        copy_row = dict(row)
        if copy_row.get("assigned_at", "").strip():
            shifted = rec._parse_ts(copy_row["assigned_at"]) + timedelta(
                minutes=300)
            copy_row["assigned_at"] = shifted.isoformat()
        out.append(copy_row)
    return rows, out


class RecoverySuccessTest(unittest.TestCase):
    def test_assignment_recovery_verified(self):
        result = run_recovery_test("CHS-ASSIGN-01", "restore-assignments")
        self.assertEqual(result["status"], "verified")
        self.assertTrue(result["target_resolved"])
        self.assertTrue(all(result["regression"].values()))
        self.assertEqual(result["post_repair"],
                         result["baseline"])
        self.assertEqual(result["post_repair"]["CHS-B"]["classification"],
                         "confirmed-miss")
        self.assertEqual(validate_recovery_result(result)["status"],
                         "consistent")

    def test_acknowledgment_recovery_verified(self):
        result = run_recovery_test("CHS-ACK-01", "reconcile-feed")
        self.assertEqual(result["status"], "verified")
        self.assertTrue(result["target_resolved"])
        self.assertTrue(all(result["regression"].values()))
        post = result["post_repair"]
        for case, measurement in post.items():
            self.assertEqual(measurement["feed_ack"],
                             measurement["source_ack"])
        self.assertEqual(validate_recovery_result(result)["status"],
                         "consistent")

    def test_window_returns_not_tested(self):
        result = run_recovery_test("CHS-WINDOW-01", "none-available")
        self.assertEqual(result["status"], "not-tested")
        self.assertIsNone(result["post_repair"])
        self.assertIn("Recovery not tested — insufficient verified "
                      "post-repair evidence", result["note"])
        self.assertEqual(validate_recovery_result(result)["status"],
                         "consistent")

    def test_reproducibility(self):
        first = run_recovery_test("CHS-ASSIGN-01", "restore-assignments")
        second = run_recovery_test("CHS-ASSIGN-01", "restore-assignments")
        self.assertEqual(first, second)

    def test_listed_repairs(self):
        listed = {(s["scenario_id"], s["repair_id"])
                  for s in list_recovery_scenarios()}
        self.assertIn(("CHS-ASSIGN-01", "restore-assignments"), listed)
        self.assertIn(("CHS-ACK-01", "reconcile-feed"), listed)


class AdversarialRepairTest(unittest.TestCase):
    def setUp(self):
        rows, faulted_rows = faulted_assign_rows()
        self.assign_base = measure_assign(rows)
        self.assign_fault = measure_assign(faulted_rows)
        source = {r["case_id"]: r["ack_at"]
                  for r in rec._read_csv("ack_source.csv")}
        feed = {r["case_id"]: r["ack_at"]
                for r in rec._read_csv("ack_feed.csv")}
        faulted_feed = dict(feed)
        faulted_feed.pop("CHS-A", None)
        self.ack_source = source
        self.ack_base = measure_feed(source, feed)
        self.ack_fault = measure_feed(source, faulted_feed)

    def judge_assign(self, repaired):
        return evaluate_repair(
            "CHS-ASSIGN-01", "restore-assignments", "fault",
            self.assign_base, self.assign_fault, repaired, ["test change"])

    def judge_ack(self, repaired, changes=("test change",)):
        return evaluate_repair(
            "CHS-ACK-01", "reconcile-feed", "fault",
            self.ack_base, self.ack_fault, repaired, list(changes))

    def test_noop_repair_rejected(self):
        result = self.judge_assign(dict(self.assign_fault))
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["target_resolved"])

    def test_delete_evidence_rejected(self):
        repaired = {c: m for c, m in self.assign_fault.items()
                    if c != "CHS-A"}
        result = self.judge_assign(repaired)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["regression"]["baseline_restored"])

    def test_duplicate_acknowledgment_rejected(self):
        repaired = dict(self.ack_base)
        repaired["CHS-X"] = {"source_ack": None, "feed_ack": "2026-09-10T12:00:00",
                             "discrepancy": True}
        result = self.judge_ack(repaired)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["regression"]["no_unexpected_records"])

    def test_invalid_order_repair_rejected(self):
        rows, _ = faulted_assign_rows()
        bad = [dict(r, assigned_at="2026-09-10T13:20:00") if r["case_id"] == "CHS-A" else dict(r)
               for r in rows]
        repaired = measure_assign(bad)
        self.assertTrue(repaired["CHS-A"]["ordering_anomaly"])
        result = self.judge_assign(repaired)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["regression"]["no_new_anomaly"])

    def test_unrelated_modification_rejected(self):
        rows, _ = faulted_assign_rows()
        bad = [dict(r, ack_at="2026-09-10T09:00:00") if r["case_id"] == "CHS-B" else dict(r)
               for r in rows]
        result = self.judge_assign(measure_assign(bad))
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["regression"]["baseline_restored"])

    def test_hidden_preexisting_violation_rejected(self):
        rows, _ = faulted_assign_rows()
        bad = [dict(r, ack_at="2026-09-10T09:00:00") if r["case_id"] == "CHS-B" else dict(r)
               for r in rows]
        repaired = measure_assign(bad)
        self.assertNotEqual(repaired["CHS-B"]["classification"],
                            "confirmed-miss")
        result = self.judge_assign(repaired)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["regression"]["preexisting_miss_preserved"])

    def test_status_correctness_enforced(self):
        failed = self.judge_assign(dict(self.assign_fault))
        self.assertEqual(failed["status"], "failed")
        claimed = dict(failed, status="verified")
        with self.assertRaises(ChaosRecoveryError) as cm:
            validate_recovery_result(claimed)
        self.assertEqual(cm.exception.code, "unverified-claim")


class RecoveryHygieneTest(unittest.TestCase):
    def test_malformed_results_rejected(self):
        good = run_recovery_test("CHS-ACK-01", "reconcile-feed")
        for mutate, code in [
            ({"schema": "ChaosRecoveryV9"}, "bad-schema"),
            ({"run_id": "0" * 64}, "run-mismatch"),
            ({"status": "recovered"}, "bad-status"),
        ]:
            tampered = dict(good, **mutate)
            with self.assertRaises(ChaosRecoveryError, msg=code) as cm:
                validate_recovery_result(tampered)
            self.assertEqual(cm.exception.code, code)

    def test_invalid_pairing_rejected(self):
        with self.assertRaises(ChaosRecoveryError) as cm:
            run_recovery_test("CHS-ACK-01", "restore-assignments")
        self.assertEqual(cm.exception.code, "unknown-pairing")
        with self.assertRaises(ChaosRecoveryError):
            run_recovery_test("CHS-NOPE-99", "reconcile-feed")

    def test_source_reference_integrity(self):
        for sid, rid in (("CHS-ASSIGN-01", "restore-assignments"),
                         ("CHS-ACK-01", "reconcile-feed")):
            result = run_recovery_test(sid, rid)
            for ref in result["refs"]:
                self.assertTrue((ROOT / ref).is_file(), msg=ref)

    def test_fixture_immutability(self):
        before = hashes(FIXTURES_DIR)
        run_recovery_test("CHS-ASSIGN-01", "restore-assignments")
        run_recovery_test("CHS-ACK-01", "reconcile-feed")
        run_recovery_test("CHS-WINDOW-01", "none-available")
        self.assertEqual(hashes(FIXTURES_DIR), before)

    def test_no_mission_or_receipt_side_effects(self):
        from backend.server import handle_request, new_context

        ctx = new_context()
        _, before, _ = handle_request("GET", "/api/mission", None, ctx)
        case_before = hashes(CASE_DIR)
        receipts_before = hashes(RECEIPTS_DIR)
        run_recovery_test("CHS-ASSIGN-01", "restore-assignments")
        _, after, _ = handle_request("GET", "/api/mission", None, ctx)
        self.assertEqual(before, after)
        self.assertEqual(hashes(CASE_DIR), case_before)
        self.assertEqual(hashes(RECEIPTS_DIR), receipts_before)

    def test_no_provider_or_network_capability(self):
        import re

        source = Path(rec.__file__).read_text()
        for token in ("MODEL_API_KEY", "meta_adapter", "model_client",
                      "SRC-FEED", "09:40", "from .", "from backend",
                      "import backend"):
            self.assertNotIn(token, source, msg=token)
        for pattern in (r"^\s*import\s+(subprocess|socket|urllib|http|ssl|os)\b",
                        r"^\s*from\s+(subprocess|socket|urllib|http|ssl|os)\b",
                        r"\bos\.(system|popen|exec)",
                        r"subprocess\.\w+\("):
            self.assertIsNone(re.search(pattern, source, re.MULTILINE),
                              msg=pattern)

    def test_engine_yardstick_consistency(self):
        from backend.chaos_simulation import run_simulation

        classes = set()
        for sid in ("CHS-ASSIGN-01", "CHS-ACK-01"):
            classes |= json_classes(run_simulation(sid, "baseline"),
                                    run_simulation(sid, "injected"))
        self.assertIn("confirmed-miss", classes)
        self.assertIn("acknowledged", classes)
        self.assertEqual(
            measure_assign(rec._read_csv("assign.csv")),
            run_simulation("CHS-ASSIGN-01", "baseline")["observations"])

    def test_takes_no_mission_state(self):
        for name in ("run_recovery_test", "evaluate_repair",
                     "validate_recovery_result", "list_recovery_scenarios"):
            params = inspect.signature(getattr(rec, name)).parameters
            for banned in ("ctx", "context", "mission", "experiment"):
                self.assertNotIn(banned, params)


def json_classes(*results):
    return {m.get("classification") for r in results
            for m in r["observations"].values()}


if __name__ == "__main__":
    unittest.main()
