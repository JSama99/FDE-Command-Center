"""MC-004b contract tests for the PROPOSED MissionReceiptLinkV1 linkage.

Nothing tested here exists in the backend yet: `check_link` and
`linked_response` below are a test-local reference for the proposed
contract rules (see docs/receipt-link-contract.md), not shipped
behavior. Gap tests (no run id, no endpoint) assert the real code.
All receipt reads are read-only; no receipts are created or modified.
"""

import copy
import hashlib
import json
import unittest
from pathlib import Path

from backend.experiment import OUTCOME_MARKERS
from backend.receipt import load_receipt, verify_receipt
from backend.server import new_context

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL = ("1902c485a31f4e45", "10d84a313fd44022")


def check_link(link, receipts, run, authenticated=True):
    """Reference implementation of proposed link validation.

    Returns (ok, checks). Refuses on missing/ambiguous/mismatched/
    conflicting/tampered/unauthenticated cases.
    """
    checks = {}
    if not authenticated:
        return False, {"auth": "refused-unauthenticated"}
    if not isinstance(link, dict) or link.get("contract") != "MissionReceiptLinkV1":
        return False, {"contract": "unknown"}
    if link.get("status") != "active" or link.get("superseded_by") is not None:
        return False, {"link-state": "not-active"}
    receipt = receipts.get(link.get("receipt_id"))
    if receipt is None:
        return False, {"receipt": "missing"}
    checks["receipt-exists"] = True
    if not (receipt.get("case_id") == link.get("case_id") == run.get("case_id")):
        return False, {"case": "mismatch"}
    checks["case"] = "match"
    stored = hashlib.sha256(json.dumps(
        receipt["investigation"], sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    if not (stored == receipt.get("investigation_sha256")
            == link.get("receipt_investigation_sha256")):
        return False, {"integrity": "fail"}
    checks["integrity"] = "pass"
    if link.get("mission_run_id") != run.get("mission_run_id"):
        return False, {"run": "mismatch"}
    checks["run"] = "authoritative"
    if link.get("prediction_sha256") != run.get("prediction_sha256"):
        return False, {"prediction": "mismatch"}
    checks["prediction"] = "match"
    return True, checks


def linked_response(link, receipt, adjudication_state, revealed):
    """Reference minimal response builder: strips outcome markers unless
    the run's own reveal authorized them; never includes paths/secrets."""
    blob = {"finding": receipt.get("finding", ""), "detail": receipt.get("detail", "")}
    text = json.dumps(blob)
    if not revealed and any(m in text for m in OUTCOME_MARKERS):
        return {"error": "no-linked-receipt"}
    return {
        "receipt_id": link["receipt_id"],
        "case_id": receipt["case_id"],
        "investigation_sha256": receipt["investigation_sha256"],
        "adjudication": adjudication_state,
    }


def valid_link(run_id="mr-test-run-1", receipt_id=HISTORICAL[0],
               pred="p" * 64, case="case-001"):
    receipt = load_receipt(receipt_id)
    return {
        "contract": "MissionReceiptLinkV1",
        "mission_run_id": run_id,
        "mission_id": "mission-case-001",
        "case_id": case,
        "experiment_id": "EXP-001",
        "prediction_sha256": pred,
        "receipt_id": receipt_id,
        "receipt_investigation_sha256": receipt["investigation_sha256"],
        "linked_at_utc": "2026-10-28T00:00:00+00:00",
        "link_authority": "human-operator",
        "link_event": "post-assessment-link",
        "status": "active",
        "superseded_by": None,
    }, {
        run_id: {"mission_run_id": run_id, "case_id": case,
                 "prediction_sha256": pred},
    }


class LinkContractTest(unittest.TestCase):
    def receipts(self):
        return {rid: load_receipt(rid) for rid in HISTORICAL}

    def test_valid_explicit_link(self):
        link, runs = valid_link()
        ok, checks = check_link(link, self.receipts(), runs[link["mission_run_id"]])
        self.assertTrue(ok)
        self.assertEqual(checks["integrity"], "pass")

    def test_two_receipts_same_case_no_link_refused(self):
        receipts = self.receipts()
        self.assertEqual({r["case_id"] for r in receipts.values()}, {"case-001"})
        ok, checks = check_link(None, receipts,
                                {"mission_run_id": "mr-x", "case_id": "case-001",
                                 "prediction_sha256": "p" * 64})
        self.assertFalse(ok)

    def test_missing_receipt_refused(self):
        link, runs = valid_link()
        link = dict(link, receipt_id="deadbeefdeadbeef")
        ok, checks = check_link(link, self.receipts(), runs[link["mission_run_id"]])
        self.assertFalse(ok)
        self.assertIn("receipt", checks)

    def test_mismatched_case_refused(self):
        link, runs = valid_link(case="case-999")
        ok, checks = check_link(link, self.receipts(), runs[link["mission_run_id"]])
        self.assertFalse(ok)
        self.assertIn("case", checks)

    def test_mismatched_investigation_hash_refused(self):
        link, runs = valid_link()
        link = dict(link, receipt_investigation_sha256="0" * 64)
        ok, checks = check_link(link, self.receipts(), runs[link["mission_run_id"]])
        self.assertFalse(ok)
        self.assertIn("integrity", checks)

    def test_conflicting_links_refused(self):
        # Two active links for one run is not a valid link payload: the
        # registry must enforce unique-active per run (contract Section 5).
        link, runs = valid_link()
        other = dict(link, receipt_id=HISTORICAL[1],
                     receipt_investigation_sha256=self.receipts()[HISTORICAL[1]]["investigation_sha256"])
        self.assertNotEqual(link["receipt_id"], other["receipt_id"])
        ok, _ = check_link([link, other], self.receipts(), runs[link["mission_run_id"]])
        self.assertFalse(ok)

    def test_pending_adjudication_reported_not_hidden(self):
        for rid in HISTORICAL:
            self.assertEqual(load_receipt(rid)["adjudication_status"], "pending")
        link, _ = valid_link()
        resp = linked_response(link, self.receipts()[link["receipt_id"]],
                               "pending", revealed=True)
        self.assertEqual(resp["adjudication"], "pending")

    def test_tampered_receipt_fails_verification(self):
        receipts = self.receipts()
        tampered = copy.deepcopy(receipts[HISTORICAL[0]])
        tampered["investigation"] = {"observations": []}
        link, runs = valid_link()
        ok, _ = check_link(link, {HISTORICAL[0]: tampered},
                           runs[link["mission_run_id"]])
        self.assertFalse(ok)

    def test_mission_reset_does_not_reuse_link(self):
        link, runs = valid_link(run_id="mr-old-run")
        fresh_run = {"mission_run_id": "mr-new-run", "case_id": "case-001",
                     "prediction_sha256": "p" * 64}
        ok, _ = check_link(link, self.receipts(), fresh_run)
        self.assertFalse(ok)

    def test_unauthenticated_lookup_refused(self):
        link, runs = valid_link()
        ok, checks = check_link(link, self.receipts(),
                                runs[link["mission_run_id"]],
                                authenticated=False)
        self.assertFalse(ok)
        self.assertIn("auth", checks)

    def test_hidden_outcome_excluded_until_reveal(self):
        link, _ = valid_link()
        poisoned = dict(self.receipts()[link["receipt_id"]],
                        detail="ack at 09:40 token SRC-FEED-GAP-09:40")
        self.assertEqual(linked_response(link, poisoned, "pending", revealed=False),
                         {"error": "no-linked-receipt"})
        resp = linked_response(link, poisoned, "pending", revealed=True)
        self.assertEqual(resp["receipt_id"], link["receipt_id"])

    def test_historical_receipts_immutable(self):
        paths = {rid: ROOT / "evaluator-private" / "receipts" / rid / "receipt.json"
                 for rid in HISTORICAL}
        before = {rid: p.read_bytes() for rid, p in paths.items()}
        for rid in HISTORICAL:
            self.assertEqual(verify_receipt(rid)["checks"]["integrity"], "pass")
        after = {rid: p.read_bytes() for rid, p in paths.items()}
        self.assertEqual(before, after)


class ArchitectureGapTest(unittest.TestCase):
    def test_mission_run_identity_is_in_memory_only(self):
        # MC-004c: contexts carry a server-minted mission_run_id, but it is
        # still in-memory and case-scoped — no persistence, no linkage.
        from backend.mission import MISSION_ID, new_mission_state

        self.assertEqual(MISSION_ID, "mission-case-001")
        state = new_mission_state()
        self.assertRegex(state["mission_run_id"], r"^mr-[0-9a-f]{16}$")
        ctx = new_context()
        self.assertIn("mission_run_id", ctx["mission"])
        self.assertNotIn("mission_run_id", ctx["experiment"])

    def test_no_receipt_routes_or_serving(self):
        server = (ROOT / "backend" / "server.py").read_text()
        self.assertNotIn("/api/receipt", server)
        self.assertNotIn("evaluator-private", server)


if __name__ == "__main__":
    unittest.main()
