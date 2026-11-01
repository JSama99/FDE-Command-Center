"""MC-008.3: offline mission-bound receipt demonstration.

A real committed mission run reaches assessed; the deterministic
offline investigation is receipted with existing verified mechanisms;
the existing CLI registry links and verifies the association. All in
temporary directories. No provider calls, no historical modification,
no server changes.
"""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from backend import link_registry
from backend.link_registry import LinkError
from backend.investigation import build_offline_investigation
from backend.mission_store import load_snapshot
from backend.persistence import boot_context
from backend.receipt import write_receipt
from backend.server import handle_request

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL = ["10d84a313fd44022", "1902c485a31f4e45"]
PREDICTION = {
    "hypothesis_id": "H-ACK", "expected_finding": "ack-found",
    "expected_observation": "Source holds a case-003 ack missing.",
    "criteria": "ack-found supports H-ACK.",
    "refs": ["case-003", "events.csv"],
}


def call(ctx, method, target, body=None):
    raw = None if body is None else json.dumps(body).encode("utf-8")
    return handle_request(method, target, raw, ctx)


def run_demo(case, tmp):
    """Full offline demonstration. Returns (ctx, snapshot, receipt)."""
    store = str(Path(tmp) / "store")
    links = str(Path(tmp) / "links")
    receipts = str(Path(tmp) / "receipts")
    Path(links).mkdir()
    ctx, status, _ = boot_context(ROOT, store)
    case.assertEqual(status, "fresh")
    for method, target, body in [
            ("POST", "/api/mission/diagnostic", {"choice": "feed-probe"}),
            ("POST", "/api/experiment/predict", PREDICTION),
            ("POST", "/api/experiment/reveal", None),
            ("POST", "/api/experiment/assess", None)]:
        status, _, _ = call(ctx, method, target, body)
        case.assertEqual(status, 200, msg=target)
    run = ctx["mission"]["mission_run_id"]
    snapshot = load_snapshot(store, run)
    investigation = build_offline_investigation(ROOT)["investigation"]
    receipt = write_receipt(investigation, None, ROOT, receipts)
    record = link_registry.create_link(
        links, snapshot, receipt, "post-assessment-link",
        "mc-008.3-demo", base_dir=ROOT)
    return ctx, snapshot, receipt, record, tmp


class DemonstrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_mission_bound_association_verifies(self):
        ctx, snapshot, receipt, record, _ = run_demo(self, self.tmp.name)
        self.assertEqual(record["status"], "active")
        self.assertEqual(record["mission_run_id"],
                         ctx["mission"]["mission_run_id"])
        self.assertEqual(record["receipt_id"], receipt["receipt_id"])
        self.assertEqual(record["link_event"], "post-assessment-link")
        self.assertTrue(receipt["synthetic"])
        result = link_registry.verify_link(record, snapshot, receipt,
                                           base_dir=ROOT)
        self.assertEqual(result["state"], "verified")

    def test_event_and_revision_binding_exact(self):
        _, snapshot, receipt, record, _ = run_demo(self, self.tmp.name)
        self.assertEqual(record["prediction_sha256"],
                         snapshot["prediction"]["hash"])
        self.assertEqual(record["receipt_investigation_sha256"],
                         receipt["investigation_sha256"])
        self.assertEqual(record["snapshot_revision"],
                         snapshot["snapshot_revision"])

    def test_verification_after_revision_advancement(self):
        ctx, snapshot, receipt, record, _ = run_demo(self, self.tmp.name)
        _, proposal, _ = call(ctx, "GET", "/api/mission/proposal")
        call(ctx, "POST", "/api/mission/intervention", {
            "decision": "approve", "note": "Smallest step.",
            "proposal_id": proposal["proposal_id"],
            "proposal_version": proposal["version"]})
        store = str(Path(self.tmp.name) / "store")
        newer = load_snapshot(store, ctx["mission"]["mission_run_id"])
        result = link_registry.verify_link(record, newer, receipt,
                                           base_dir=ROOT)
        self.assertEqual(result["state"], "verified")

    def test_wrong_mission_rejected(self):
        _, snapshot, receipt, record, _ = run_demo(self, self.tmp.name)
        other = str(Path(self.tmp.name) / "other")
        ctx2, _, _ = boot_context(ROOT, other)
        call(ctx2, "POST", "/api/mission/diagnostic",
             {"choice": "feed-probe"})
        call(ctx2, "POST", "/api/experiment/predict", PREDICTION)
        call(ctx2, "POST", "/api/experiment/reveal", None)
        call(ctx2, "POST", "/api/experiment/assess", None)
        other_snap = load_snapshot(
            other, ctx2["mission"]["mission_run_id"])
        result = link_registry.verify_link(record, other_snap, receipt,
                                           base_dir=ROOT)
        self.assertEqual(result["state"], "rejected")
        self.assertIn("mission_run_id-mismatch", result["reasons"])

    def test_wrong_event_and_proposal_rejected(self):
        ctx, snapshot, receipt, _, _ = run_demo(self, self.tmp.name)
        with self.assertRaises(LinkError) as cm:
            link_registry.create_link(
                str(Path(self.tmp.name) / "links"), snapshot, receipt,
                "audit-view-link", "op", base_dir=ROOT)
        self.assertEqual(cm.exception.code, "event-not-ready")
        _, proposal, _ = call(ctx, "GET", "/api/mission/proposal")
        call(ctx, "POST", "/api/mission/intervention", {
            "decision": "approve", "note": "Step.",
            "proposal_id": proposal["proposal_id"],
            "proposal_version": proposal["version"]})
        store = str(Path(self.tmp.name) / "store")
        decided = load_snapshot(store, ctx["mission"]["mission_run_id"])
        record = link_registry.create_link(
            str(Path(self.tmp.name) / "links"), decided, receipt,
            "post-assessment-link", "op", base_dir=ROOT)
        self.assertEqual(record["proposal"]["version"], "v1")
        forged = copy.deepcopy(record)
        forged["proposal"] = {"proposal_id": "PROP-002", "version": "v9"}
        result = link_registry.verify_link(forged, decided, receipt,
                                           base_dir=ROOT)
        self.assertEqual(result["state"], "rejected")
        self.assertIn("proposal-mismatch", result["reasons"])

    def test_corrupt_receipt_rejected(self):
        _, snapshot, receipt, record, _ = run_demo(self, self.tmp.name)
        tampered = copy.deepcopy(receipt)
        tampered["investigation"]["observations"].append(
            {"text": "Inserted.", "refs": ["policy"],
             "basis": "verified-quote"})
        result = link_registry.verify_link(record, snapshot, tampered,
                                           base_dir=ROOT)
        self.assertEqual(result["state"], "rejected")
        self.assertIn("integrity-fail", result["reasons"])

    def test_missing_provenance_rejected(self):
        _, snapshot, _, _, _ = run_demo(self, self.tmp.name)
        forged = {
            "receipt_id": "test-forged",
            "created_at_utc": "2099-01-01T00:00:00+00:00",
            "case_id": "case-001",
            "evidence_manifest": receipt_manifest(),
            "investigation": {
                "observations": [{"text": "Nothing cites anything.",
                                  "refs": ["no-such-doc"],
                                  "basis": "computed"}],
                "competing_hypotheses": [],
                "unresolved_questions": ["q"],
                "diagnostic_experiments": [],
                "provisional_recommendation": {
                    "text": "Wait.", "refs": ["events.csv"],
                    "requires_human_approval": True,
                    "executes_production_change": False},
                "counter_evidence": []},
        }
        forged["investigation_sha256"] = link_registry._sha256(
            link_registry._canonical(forged["investigation"]))
        with self.assertRaises(LinkError) as cm:
            link_registry.create_link(
                str(Path(self.tmp.name) / "links"), snapshot, forged,
                "post-assessment-link", "op", base_dir=ROOT)
        self.assertEqual(cm.exception.code, "provenance-fail")

    def test_duplicate_and_revoke(self):
        _, snapshot, receipt, record, _ = run_demo(self, self.tmp.name)
        links = str(Path(self.tmp.name) / "links")
        second = link_registry.create_link(
            links, snapshot, receipt, "post-assessment-link", "op2",
            base_dir=ROOT)
        stored = {e["link_id"]: e for e in link_registry.load_registry(
            links)["links"]}
        self.assertEqual(stored[record["link_id"]]["status"], "superseded")
        self.assertEqual(link_registry.verify_link(
            stored[record["link_id"]], snapshot, receipt,
            base_dir=ROOT)["reasons"], ["superseded"])
        link_registry.revoke_link(links, second["link_id"], "op2")
        stored = {e["link_id"]: e for e in link_registry.load_registry(
            links)["links"]}
        self.assertEqual(link_registry.verify_link(
            stored[second["link_id"]], snapshot, receipt,
            base_dir=ROOT)["reasons"], ["revoked"])

    def test_no_production_execution_claim(self):
        _, _, receipt, record, tmp = run_demo(self, self.tmp.name)
        blob = json.dumps(record) + json.dumps(receipt)
        # The records positively assert non-execution; no executed flag
        # is ever set and no event type names execution.
        self.assertIn('"executes_production_change": false', blob)
        self.assertNotIn('"executed": true', blob)
        self.assertNotIn("execut", record["link_event"])
        path = next((Path(tmp) / "receipts").rglob("receipt.json"))
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        link_registry.verify_link(record, load_snapshot(
            str(Path(tmp) / "store"), record["mission_run_id"]), receipt,
            base_dir=ROOT)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         before)

    def test_historical_receipts_still_unlinked(self):
        _, snapshot, _, _, tmp = run_demo(self, self.tmp.name)
        links = str(Path(tmp) / "links")
        before = {}
        for rid in HISTORICAL:
            path = ROOT / "evaluator-private" / "receipts" / rid / \
                "receipt.json"
            before[rid] = hashlib.sha256(path.read_bytes()).hexdigest()
            receipt = json.loads(path.read_text())
            with self.assertRaises(LinkError):
                link_registry.create_link(links, snapshot, receipt,
                                          "post-assessment-link", "op",
                                          base_dir=ROOT)
        for rid in HISTORICAL:
            path = ROOT / "evaluator-private" / "receipts" / rid / \
                "receipt.json"
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                             before[rid])

    def test_zero_provider_calls_and_fixtures_intact(self):
        import backend.server as server_mod

        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted((ROOT / "fixtures" / "case-001").iterdir())
                  if p.is_file()}
        real = server_mod.MetaModelAdapter
        server_mod.MetaModelAdapter = lambda: (_ for _ in ()).throw(
            AssertionError("provider must not be called"))
        try:
            run_demo(self, self.tmp.name)
        finally:
            server_mod.MetaModelAdapter = real
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted((ROOT / "fixtures" / "case-001").iterdir())
                 if p.is_file()}
        self.assertEqual(before, after)


def receipt_manifest():
    from backend.receipt import evidence_manifest

    return evidence_manifest(ROOT)


if __name__ == "__main__":
    unittest.main()
