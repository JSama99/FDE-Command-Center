"""MC-008.1: receipt-linkage audit facts.

Offline only. Establishes what today's receipts and mission snapshots
do and do not contain, so no future link can rest on an assumption.
Historical receipts are read, never modified. No provider calls.
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECEIPTS = ROOT / "evaluator-private" / "receipts"


def stored_receipt_ids():
    return sorted(p.name for p in RECEIPTS.iterdir() if p.is_dir())


class HistoricalReceiptFactsTest(unittest.TestCase):
    def test_historical_receipts_carry_no_mission_identity(self):
        ids = stored_receipt_ids()
        self.assertTrue(ids)
        for rid in ids:
            receipt = json.loads((RECEIPTS / rid / "receipt.json").read_text())
            for field in ("mission_run_id", "mission_id", "experiment_id",
                          "prediction_sha256", "proposal_id", "decision",
                          "link_event", "link_authority"):
                self.assertNotIn(field, receipt, msg=f"{rid}:{field}")
            self.assertEqual(receipt["case_id"], "case-001")
            investigation = json.dumps(receipt["investigation"])
            self.assertNotIn("mission_run_id", investigation, msg=rid)

    def test_historical_receipt_integrity_holds(self):
        from backend.receipt import verify_receipt

        for rid in stored_receipt_ids():
            findings = verify_receipt(rid)
            self.assertEqual(findings["checks"]["integrity"], "pass",
                             msg=rid)

    def test_no_link_route_or_historical_linkage(self):
        # MC-008.2 added an offline registry module; the server still has
        # no link route and no historical receipt is linked.
        server_src = (ROOT / "backend" / "server.py").read_text()
        self.assertNotIn("link_registry", server_src)
        self.assertNotIn("MissionReceiptLinkV1", server_src)
        self.assertNotIn("/api/receipt", server_src)
        self.assertNotIn("/api/link", server_src)


class MissionSideLinkFieldsTest(unittest.TestCase):
    def test_snapshot_carries_every_mission_side_link_field(self):
        import tempfile

        from backend.mission_snapshot import build_snapshot
        from backend.persistence import boot_context
        from backend.server import handle_request

        prediction = {
            "hypothesis_id": "H-ACK", "expected_finding": "ack-found",
            "expected_observation": "Source holds a case-003 ack.",
            "criteria": "ack-found supports H-ACK.",
            "refs": ["case-003", "events.csv"],
        }

        def call(ctx, method, target, body=None):
            raw = None if body is None else json.dumps(body).encode()
            return handle_request(method, target, raw, ctx)

        with tempfile.TemporaryDirectory() as tmp:
            store = str(Path(tmp) / "store")
            ctx, _, _ = boot_context(ROOT, store)
            call(ctx, "POST", "/api/mission/diagnostic",
                 {"choice": "feed-probe"})
            call(ctx, "POST", "/api/experiment/predict", prediction)
            call(ctx, "POST", "/api/experiment/reveal", None)
            call(ctx, "POST", "/api/experiment/assess", None)
            _, proposal, _ = call(ctx, "GET", "/api/mission/proposal")
            call(ctx, "POST", "/api/mission/intervention", {
                "decision": "approve", "note": "Smallest reversible step.",
                "proposal_id": proposal["proposal_id"],
                "proposal_version": proposal["version"]})
            from backend.receipt import evidence_manifest

            body = build_snapshot(ctx, evidence_manifest(ROOT), 5, "t")
            self.assertRegex(body["mission_run_id"], r"^mr-[0-9a-f]{16}$")
            self.assertIn("hash", body["prediction"])
            self.assertIn(body["assessment"]["result"],
                          ("supported", "contradicted", "unresolved"))
            # Production snapshots carry proposal:null (attach_proposal is
            # test-only); binding survives in the verbatim intervention
            # record and by deterministic re-derivation.
            self.assertIsNone(body["proposal"])
            self.assertEqual(body["intervention"]["proposal"]["proposal_id"],
                             proposal["proposal_id"])
            self.assertEqual(body["intervention"]["proposal"]["version"],
                             proposal["version"])
            self.assertEqual(body["intervention"]["decision"], "approve")
            self.assertIs(body["intervention"]["executed"], False)


if __name__ == "__main__":
    unittest.main()
