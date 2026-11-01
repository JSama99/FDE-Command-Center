"""MC-004d offline validation for the PROPOSED MissionSnapshotV1 contract.

`encode_snapshot`, `commit_snapshot`, and `recover_snapshot` below are
test-local reference implementations of docs/mission-persistence-contract.md
— NOT shipped behavior; backend runtime is untouched. Real backend
functions build the in-memory states under test; only plain-dict copies
enter the reference codec. Storage is confined to per-test temp dirs.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from backend.experiment import public_view
from backend.mission import choose_diagnostic, decide_intervention
from backend.experiment import assess as assess_experiment
from backend.experiment import build_registry, lock_prediction, reveal_outcome
from backend.receipt import evidence_manifest
from backend.server import new_context

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "MissionSnapshotV1"
PREDICTION = {
    "hypothesis_id": "H-ACK",
    "expected_finding": "ack-found",
    "expected_observation": "Source log holds a case-003 ack missing from the feed.",
    "criteria": "ack-found supports H-ACK; no-ack supports H-QUEUE.",
    "refs": ["case-003", "events.csv"],
}


class SnapshotError(ValueError):
    pass


def encode_snapshot(state, revision, manifest):
    body = {
        "schema": SCHEMA,
        "snapshot_revision": revision,
        "mission_run_id": state["mission_run_id"],
        "mission_id": "mission-case-001",
        "case_id": "case-001",
        "experiment_id": "EXP-001",
        "mission": {k: state[k] for k in ("diagnostic", "audit_viewed")},
        "prediction": state.get("prediction"),
        "outcome": state.get("outcome"),
        "assessment": state.get("assessment"),
        "proposal": state.get("proposal_ref"),
        "intervention": state.get("intervention"),
        "source_manifest": manifest,
    }
    if body["outcome"] is not None and body["prediction"] is None:
        raise SnapshotError("outcome without locked prediction")
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"))
    body["snapshot_sha256"] = hashlib.sha256(blob.encode()).hexdigest()
    return body


def commit_snapshot(store, run_id, body, expected_revision):
    store = Path(store)
    main = store / f"mission-{run_id}.json"
    if main.is_file():
        prior = json.loads(main.read_text())
        if prior.get("snapshot_revision") != expected_revision:
            raise SnapshotError("stale revision")
        (store / f"mission-{run_id}.json.prev").write_text(main.read_text())
    elif expected_revision != 0:
        raise SnapshotError("stale revision")
    if body["snapshot_revision"] != expected_revision + 1:
        raise SnapshotError("non-monotonic revision")
    tmp = store / f"mission-{run_id}.json.tmp"
    tmp.write_text(json.dumps(body, indent=2))
    tmp.replace(main)
    return body["snapshot_revision"]


def recover_snapshot(store, run_id, live_manifest):
    main = Path(store) / f"mission-{run_id}.json"
    if not main.is_file():
        return "fresh", None, "no saved state"
    try:
        body = json.loads(main.read_text())
    except json.JSONDecodeError:
        return "reject", None, "corrupted bytes"
    if body.get("schema") != SCHEMA:
        return "reject", None, "unknown schema"
    digest = body.pop("snapshot_sha256", None)
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"))
    if digest != hashlib.sha256(blob.encode()).hexdigest():
        return "reject", None, "invalid digest"
    if body.get("source_manifest") != live_manifest:
        return "quarantine", body, "manifest drift"
    if body.get("outcome") is not None and body.get("prediction") is None:
        return "reject", None, "outcome without lock"
    return "load", body, "ok"


def mission_state(ctx, proposal_ref=None):
    state = dict(ctx["mission"])
    state.update({k: ctx["experiment"].get(k) for k in
                  ("prediction", "outcome", "assessment")})
    state["proposal_ref"] = proposal_ref
    return state


def progressed_ctx():
    ctx = new_context()
    choose_diagnostic(ctx, "feed-probe")
    lock_prediction(ctx["experiment"], dict(PREDICTION),
                    build_registry(ROOT), 1700000000, origin="human-authored")
    return ctx


class SnapshotContractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manifest = evidence_manifest(ROOT)

    def test_valid_round_trip_preserves_run_identity(self):
        ctx = progressed_ctx()
        body = encode_snapshot(mission_state(ctx), 1, self.manifest)
        rev = commit_snapshot(self.tmp.name, ctx["mission"]["mission_run_id"], body, 0)
        status, loaded, _ = recover_snapshot(
            self.tmp.name, ctx["mission"]["mission_run_id"], self.manifest)
        self.assertEqual((status, rev), ("load", 1))
        self.assertEqual(loaded["mission_run_id"], ctx["mission"]["mission_run_id"])
        self.assertEqual(loaded["prediction"], ctx["experiment"]["prediction"])

    def test_prediction_lock_immutability(self):
        # Post-commit edits fail the digest and never load as truth.
        # (Backend already rejects relocking; the snapshot layer refuses
        # to present altered bytes.)
        ctx = progressed_ctx()
        good = encode_snapshot(mission_state(ctx), 1, self.manifest)
        commit_snapshot(self.tmp.name, ctx["mission"]["mission_run_id"], good, 0)
        main = Path(self.tmp.name) / f"mission-{ctx['mission']['mission_run_id']}.json"
        edited = json.loads(main.read_text())
        edited["prediction"]["expected_finding"] = "no-ack"
        main.write_text(json.dumps(edited))
        status, _, reason = recover_snapshot(
            self.tmp.name, ctx["mission"]["mission_run_id"], self.manifest)
        self.assertEqual((status, reason), ("reject", "invalid digest"))

    def test_proposal_decision_binding_preserved(self):
        from backend.mission import intervention_proposal

        ctx = progressed_ctx()
        reveal_outcome(ctx["experiment"], 1700000001)
        assess_experiment(ctx["experiment"])
        proposal = intervention_proposal(ctx)
        state = mission_state(ctx, {"proposal_id": proposal["proposal_id"],
                                    "version": proposal["version"]})
        body = encode_snapshot(state, 1, self.manifest)
        self.assertEqual(body["proposal"], {"proposal_id": proposal["proposal_id"],
                                            "version": proposal["version"]})
        commit_snapshot(self.tmp.name, ctx["mission"]["mission_run_id"], body, 0)
        _, loaded, _ = recover_snapshot(
            self.tmp.name, ctx["mission"]["mission_run_id"], self.manifest)
        self.assertEqual(loaded["proposal"]["proposal_id"], proposal["proposal_id"])

    def test_rejected_transition_advances_nothing(self):
        ctx = progressed_ctx()
        body = encode_snapshot(mission_state(ctx), 1, self.manifest)
        commit_snapshot(self.tmp.name, ctx["mission"]["mission_run_id"], body, 0)
        before = (Path(self.tmp.name) / f"mission-{ctx['mission']['mission_run_id']}.json").read_bytes()
        with self.assertRaises(SnapshotError):
            commit_snapshot(self.tmp.name, ctx["mission"]["mission_run_id"], body, 0)
        after = (Path(self.tmp.name) / f"mission-{ctx['mission']['mission_run_id']}.json").read_bytes()
        self.assertEqual(before, after)

    def test_interrupted_write_never_authoritative(self):
        ctx = progressed_ctx()
        run = ctx["mission"]["mission_run_id"]
        main = Path(self.tmp.name) / f"mission-{run}.json"
        main.write_text('{"schema": "MissionSnapshotV1", "snapshot_revisi')
        status, loaded, _ = recover_snapshot(self.tmp.name, run, self.manifest)
        self.assertEqual((status, loaded), ("reject", None))

    def test_manifest_mismatch_quarantines(self):
        ctx = progressed_ctx()
        body = encode_snapshot(mission_state(ctx), 1, self.manifest)
        commit_snapshot(self.tmp.name, ctx["mission"]["mission_run_id"], body, 0)
        drifted = dict(self.manifest, **{"fixtures/case-001/events.csv": "0" * 64})
        status, loaded, reason = recover_snapshot(
            self.tmp.name, ctx["mission"]["mission_run_id"], drifted)
        self.assertEqual(status, "quarantine")
        self.assertEqual(loaded["mission_run_id"], ctx["mission"]["mission_run_id"])
        self.assertIn("drift", reason)

    def test_unknown_schema_rejected(self):
        ctx = progressed_ctx()
        body = encode_snapshot(mission_state(ctx), 1, self.manifest)
        body["schema"] = "MissionSnapshotV9"
        commit_snapshot(self.tmp.name, ctx["mission"]["mission_run_id"], body, 0)
        # Digest must be recomputed for the tampered-schema file to isolate
        # the schema check from the digest check.
        main = Path(self.tmp.name) / f"mission-{ctx['mission']['mission_run_id']}.json"
        raw = json.loads(main.read_text())
        raw.pop("snapshot_sha256")
        raw["snapshot_sha256"] = hashlib.sha256(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        main.write_text(json.dumps(raw))
        status, _, reason = recover_snapshot(
            self.tmp.name, ctx["mission"]["mission_run_id"], self.manifest)
        self.assertEqual((status, reason), ("reject", "unknown schema"))

    def test_locked_but_unrevealed_recovers_concealed(self):
        ctx = progressed_ctx()
        body = encode_snapshot(mission_state(ctx), 1, self.manifest)
        self.assertIsNone(body["outcome"])
        commit_snapshot(self.tmp.name, ctx["mission"]["mission_run_id"], body, 0)
        status, loaded, _ = recover_snapshot(
            self.tmp.name, ctx["mission"]["mission_run_id"], self.manifest)
        self.assertEqual(status, "load")
        view = public_view(ctx["experiment"])
        self.assertNotIn("outcome", view)

    def test_completed_mission_recovers_decision(self):
        from backend.mission import decide_intervention, intervention_proposal

        ctx = progressed_ctx()
        reveal_outcome(ctx["experiment"], 1700000001)
        assess_experiment(ctx["experiment"])
        proposal = intervention_proposal(ctx)
        decide_intervention(ctx, "approve",
                            "Feed reconciliation is the smallest reversible next step.",
                            proposal["proposal_id"], proposal["version"])
        body = encode_snapshot(
            mission_state(ctx, {"proposal_id": proposal["proposal_id"],
                                "version": proposal["version"]}), 1, self.manifest)
        commit_snapshot(self.tmp.name, ctx["mission"]["mission_run_id"], body, 0)
        status, loaded, _ = recover_snapshot(
            self.tmp.name, ctx["mission"]["mission_run_id"], self.manifest)
        self.assertEqual(status, "load")
        self.assertEqual(loaded["intervention"]["decision"], "approve")
        self.assertFalse(loaded["intervention"]["executed"])

    def test_concurrent_stale_revision_aborts(self):
        ctx = progressed_ctx()
        run = ctx["mission"]["mission_run_id"]
        first = encode_snapshot(mission_state(ctx), 1, self.manifest)
        commit_snapshot(self.tmp.name, run, first, 0)
        stale = encode_snapshot(mission_state(ctx), 1, self.manifest)
        with self.assertRaises(SnapshotError):
            commit_snapshot(self.tmp.name, run, stale, 0)

    def test_outcome_without_lock_rejected(self):
        ctx = new_context()
        state = mission_state(ctx)
        state["outcome"] = {"finding": "ack-found"}
        with self.assertRaises(SnapshotError):
            encode_snapshot(state, 1, self.manifest)

    def test_pending_receipt_linkage_absent(self):
        ctx = progressed_ctx()
        body = encode_snapshot(mission_state(ctx), 1, self.manifest)
        self.assertNotIn("receipt", json.dumps(body).lower())


if __name__ == "__main__":
    unittest.main()
