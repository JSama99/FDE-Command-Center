"""MC-004e: production MissionSnapshotV1 codec tests.

Real backend-created mission states through backend.mission_snapshot
(build/encode/decode/verify_against_live). No filesystem writes, no
network, no provider calls, no receipts touched.
"""

import json
import unittest
from pathlib import Path

from backend.experiment import assess as assess_experiment
from backend.experiment import build_registry, lock_prediction, reveal_outcome
from backend.mission import (choose_diagnostic, decide_intervention,
                             diagnostic_result, intervention_proposal,
                             mission_report)
from backend.mission_snapshot import (SnapshotError, attach_proposal,
                                      build_snapshot, decode_snapshot,
                                      derive_stage, encode_snapshot,
                                      verify_against_live)
from backend.receipt import evidence_manifest
from backend.server import new_context

ROOT = Path(__file__).resolve().parents[1]
PREDICTION = {
    "hypothesis_id": "H-ACK",
    "expected_finding": "ack-found",
    "expected_observation": "Source log holds a case-003 ack missing from the feed.",
    "criteria": "ack-found supports H-ACK; no-ack supports H-QUEUE.",
    "refs": ["case-003", "events.csv"],
}
NOTE = "Feed reconciliation is the smallest reversible next step."
NOW = "2026-10-29T00:00:00+00:00"


def round_trip(case, ctx, revision=1, proposal=False):
    manifest = evidence_manifest(ROOT)
    body = build_snapshot(ctx, manifest, revision, NOW)
    if proposal:
        spec = intervention_proposal(ctx)
        body = attach_proposal(body, spec["proposal_id"], spec["version"])
    raw = encode_snapshot(body)
    decoded = decode_snapshot(raw)
    checks = verify_against_live(ctx, manifest, decoded)
    case.assertEqual(decoded["mission_run_id"],
                     ctx["mission"]["mission_run_id"])
    return decoded, checks


class CodecRoundTripTest(unittest.TestCase):
    def test_fresh_mission(self):
        decoded, checks = round_trip(self, new_context())
        self.assertEqual(decoded["lifecycle_stage"], "proposed")
        self.assertIsNone(decoded["prediction"])
        self.assertEqual(checks["stage"], "consistent")

    def test_diagnostic_selected(self):
        ctx = new_context()
        choose_diagnostic(ctx, "feed-probe")
        decoded, _ = round_trip(self, ctx)
        self.assertEqual(decoded["lifecycle_stage"], "diagnostic selected")

    def test_timestamp_audit_path(self):
        ctx = new_context()
        choose_diagnostic(ctx, "timestamp-audit")
        diagnostic_result(ctx)
        decoded, checks = round_trip(self, ctx)
        self.assertTrue(decoded["mission"]["audit_viewed"])
        self.assertEqual(checks["run"], "authoritative")

    def test_prediction_locked_and_unrevealed(self):
        ctx = new_context()
        choose_diagnostic(ctx, "feed-probe")
        lock_prediction(ctx["experiment"], dict(PREDICTION),
                        build_registry(ROOT), 1700000000,
                        origin="human-authored")
        decoded, _ = round_trip(self, ctx)
        self.assertEqual(decoded["lifecycle_stage"], "prediction locked")
        self.assertIsNone(decoded["outcome"])
        self.assertEqual(decoded["prediction"]["expected_finding"], "ack-found")

    def test_revealed_and_assessed(self):
        ctx = new_context()
        choose_diagnostic(ctx, "feed-probe")
        lock_prediction(ctx["experiment"], dict(PREDICTION),
                        build_registry(ROOT), 1700000000,
                        origin="human-authored")
        reveal_outcome(ctx["experiment"], 1700000001)
        assess_experiment(ctx["experiment"])
        decoded, _ = round_trip(self, ctx)
        self.assertEqual(decoded["lifecycle_stage"], "assessed")
        self.assertEqual(decoded["assessment"]["result"], "supported")

    def test_proposal_generated(self):
        ctx = new_context()
        choose_diagnostic(ctx, "feed-probe")
        lock_prediction(ctx["experiment"], dict(PREDICTION),
                        build_registry(ROOT), 1700000000,
                        origin="human-authored")
        reveal_outcome(ctx["experiment"], 1700000001)
        assess_experiment(ctx["experiment"])
        decoded, checks = round_trip(self, ctx, proposal=True)
        self.assertEqual(decoded["proposal"]["proposal_id"], "PROP-002")
        self.assertEqual(checks["proposal"], "bound")

    def test_human_decision_recorded(self):
        ctx = new_context()
        choose_diagnostic(ctx, "feed-probe")
        lock_prediction(ctx["experiment"], dict(PREDICTION),
                        build_registry(ROOT), 1700000000,
                        origin="human-authored")
        reveal_outcome(ctx["experiment"], 1700000001)
        assess_experiment(ctx["experiment"])
        spec = intervention_proposal(ctx)
        decide_intervention(ctx, "approve", NOTE, spec["proposal_id"],
                            spec["version"])
        decoded, _ = round_trip(self, ctx, proposal=True)
        self.assertEqual(decoded["lifecycle_stage"], "decided")
        self.assertEqual(decoded["intervention"]["decision"], "approve")
        self.assertEqual(decoded["intervention"]["note"], NOTE)
        self.assertFalse(decoded["intervention"]["executed"])

    def test_completed_report_state(self):
        ctx = new_context()
        choose_diagnostic(ctx, "feed-probe")
        lock_prediction(ctx["experiment"], dict(PREDICTION),
                        build_registry(ROOT), 1700000000,
                        origin="human-authored")
        reveal_outcome(ctx["experiment"], 1700000001)
        assess_experiment(ctx["experiment"])
        spec = intervention_proposal(ctx)
        decide_intervention(ctx, "approve", NOTE, spec["proposal_id"],
                            spec["version"])
        report = mission_report(ctx)
        self.assertTrue(report)
        decoded, checks = round_trip(self, ctx, proposal=True)
        self.assertEqual(checks["manifest"], "pinned")

    def test_run_id_preserved_and_unique(self):
        first, second = new_context(), new_context()
        m1 = evidence_manifest(ROOT)
        d1 = decode_snapshot(encode_snapshot(build_snapshot(first, m1, 1, NOW)))
        d2 = decode_snapshot(encode_snapshot(build_snapshot(second, m1, 1, NOW)))
        self.assertNotEqual(d1["mission_run_id"], d2["mission_run_id"])


class CodecRejectionTest(unittest.TestCase):
    def fresh_body(self):
        return build_snapshot(new_context(), evidence_manifest(ROOT), 1, NOW)

    def reencode(self, unsigned):
        import hashlib
        blob = json.dumps(unsigned, sort_keys=True,
                          separators=(",", ":")).encode()
        unsigned["snapshot_sha256"] = hashlib.sha256(blob).hexdigest()
        return json.dumps(unsigned).encode()

    def test_missing_fields_rejected(self):
        # Only always-required fields are listed: prediction, outcome,
        # assessment, proposal, and intervention are legitimately null.
        body = self.fresh_body()
        for key in ("mission_run_id", "source_manifest", "lifecycle_stage",
                    "mission", "schema", "snapshot_revision"):
            broken = {k: v for k, v in body.items() if k != key}
            with self.assertRaises(SnapshotError, msg=key):
                decode_snapshot(self.reencode(broken))

    def test_unsupported_schema_rejected(self):
        body = self.fresh_body()
        body["schema"] = "MissionSnapshotV9"
        with self.assertRaises(SnapshotError) as cm:
            decode_snapshot(self.reencode(body))
        self.assertEqual(cm.exception.code, "bad-schema")

    def test_tampered_digest_rejected(self):
        parsed = json.loads(encode_snapshot(self.fresh_body()).decode())
        parsed["mission"]["audit_viewed"] = True
        tampered = json.dumps(parsed).encode()
        with self.assertRaises(SnapshotError) as cm:
            decode_snapshot(tampered)
        self.assertEqual(cm.exception.code, "bad-digest")

    def test_wrong_manifest_rejected_against_live(self):
        ctx = new_context()
        manifest = evidence_manifest(ROOT)
        body = build_snapshot(ctx, manifest, 1, NOW)
        drifted = dict(manifest, **{"fixtures/case-001/events.csv": "0" * 64})
        decoded = decode_snapshot(encode_snapshot(body))
        with self.assertRaises(SnapshotError) as cm:
            verify_against_live(ctx, drifted, decoded)
        self.assertEqual(cm.exception.code, "manifest-mismatch")

    def test_invalid_proposal_binding_rejected(self):
        ctx = new_context()
        choose_diagnostic(ctx, "feed-probe")
        lock_prediction(ctx["experiment"], dict(PREDICTION),
                        build_registry(ROOT), 1700000000,
                        origin="human-authored")
        reveal_outcome(ctx["experiment"], 1700000001)
        assess_experiment(ctx["experiment"])
        spec = intervention_proposal(ctx)
        manifest = evidence_manifest(ROOT)
        body = attach_proposal(build_snapshot(ctx, manifest, 1, NOW),
                               spec["proposal_id"], "v999")
        decoded = decode_snapshot(encode_snapshot(body))
        with self.assertRaises(SnapshotError) as cm:
            verify_against_live(ctx, manifest, decoded)
        self.assertEqual(cm.exception.code, "proposal-mismatch")

    def test_decision_proposal_mismatch_rejected(self):
        body = self.fresh_body()
        body["proposal"] = {"proposal_id": "PROP-002", "version": "v1"}
        body["intervention"] = {"decision": "approve", "note": NOTE,
                                "proposal": {"proposal_id": "PROP-004",
                                             "version": "v1"},
                                "executed": False}
        body["lifecycle_stage"] = "decided"
        with self.assertRaises(SnapshotError) as cm:
            decode_snapshot(self.reencode(body))
        self.assertEqual(cm.exception.code, "bad-binding")

    def test_outcome_without_prediction_rejected(self):
        body = self.fresh_body()
        body["outcome"] = {"finding": "ack-found"}
        body["lifecycle_stage"] = "result revealed"
        with self.assertRaises(SnapshotError) as cm:
            decode_snapshot(self.reencode(body))
        self.assertEqual(cm.exception.code, "gated")

    def test_execution_never_recorded(self):
        body = self.fresh_body()
        body["intervention"] = {"decision": "approve", "note": NOTE,
                                "proposal": {}, "executed": True}
        with self.assertRaises(SnapshotError):
            decode_snapshot(self.reencode(body))

    def test_malformed_run_identity_rejected(self):
        for bad in ("case-001", "mr-short", "mr-" + "Z" * 16, "", None):
            body = self.fresh_body()
            body["mission_run_id"] = bad
            with self.assertRaises(SnapshotError, msg=str(bad)) as cm:
                decode_snapshot(self.reencode(body))
            self.assertEqual(cm.exception.code, "bad-identity")

    def test_stage_inconsistency_rejected(self):
        body = self.fresh_body()
        body["lifecycle_stage"] = "assessed"
        with self.assertRaises(SnapshotError) as cm:
            decode_snapshot(self.reencode(body))
        self.assertEqual(cm.exception.code, "bad-lifecycle")

    def test_timestamp_required(self):
        ctx = new_context()
        with self.assertRaises(SnapshotError) as cm:
            build_snapshot(ctx, evidence_manifest(ROOT), 1, "")
        self.assertEqual(cm.exception.code, "bad-timestamp")

    def test_derive_stage_matches_lifecycle(self):
        self.assertEqual(derive_stage({"mission": {}, "prediction": None,
                                       "outcome": None, "assessment": None,
                                       "intervention": None}), "proposed")
        self.assertEqual(derive_stage({"mission": {"diagnostic": "feed-probe"},
                                       "prediction": {"hash": "x"},
                                       "outcome": None, "assessment": None,
                                       "intervention": None}),
                         "prediction locked")


if __name__ == "__main__":
    unittest.main()
