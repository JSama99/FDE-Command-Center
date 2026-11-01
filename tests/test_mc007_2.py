"""MC-007.2: snapshot hardening, active-run pointer, crash recovery.

Offline only, temporary directories throughout. No server wiring, no
provider calls, no receipt linkage, no fixture mutation.
"""

import copy
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend import active_run
from backend.active_run import PointerError
from backend.mission_snapshot import (SnapshotError, build_snapshot,
                                      decode_snapshot, encode_snapshot)
from backend.mission_store import StoreError, commit_snapshot
from backend.receipt import evidence_manifest
from backend.server import new_context, handle_request

ROOT = Path(__file__).resolve().parents[1]
PREDICTION = {
    "hypothesis_id": "H-ACK",
    "expected_finding": "ack-found",
    "expected_observation": "Source log holds a case-003 ack missing from the feed.",
    "criteria": "ack-found supports H-ACK; no-ack supports H-QUEUE.",
    "refs": ["case-003", "events.csv"],
}


def call(ctx, method, target, body=None):
    raw = None if body is None else json.dumps(body).encode("utf-8")
    return handle_request(method, target, raw, ctx)


def full_lifecycle_ctx(case):
    ctx = new_context()
    seq = [
        ("POST", "/api/mission/diagnostic", {"choice": "feed-probe"}),
        ("POST", "/api/experiment/predict", PREDICTION),
        ("POST", "/api/experiment/reveal", None),
        ("POST", "/api/experiment/assess", None),
        ("POST", "/api/revision/generate", {"mode": "mock"}),
    ]
    for method, target, body in seq:
        status, _, _ = call(ctx, method, target, body)
        case.assertEqual(status, 200, msg=f"{method} {target}")
    status, _, _ = call(ctx, "POST", "/api/revision/approve", {
        "decision": "approve",
        "note": "Revision is evidence-bound; H-QUEUE stays unresolved.",
    })
    case.assertEqual(status, 200)
    status, proposal, _ = call(ctx, "GET", "/api/mission/proposal")
    case.assertEqual(status, 200)
    status, _, _ = call(ctx, "POST", "/api/mission/intervention", {
        "decision": "approve",
        "note": "Bounded feed reconciliation is the smallest reversible step.",
        "proposal_id": proposal["proposal_id"],
        "proposal_version": proposal["version"],
    })
    case.assertEqual(status, 200)
    status, _, _ = call(ctx, "POST", "/api/approval", {
        "decision": "approve", "note": "AI investigation reviewed.",
    })
    case.assertEqual(status, 200)
    return ctx


def now():
    return datetime.now(timezone.utc).isoformat()


class CodecExtensionTest(unittest.TestCase):
    def test_full_lifecycle_round_trip(self):
        ctx = full_lifecycle_ctx(self)
        body = build_snapshot(ctx, evidence_manifest(), 3, now())
        live = {"revision": copy.deepcopy(ctx["experiment"]["revision"]),
                "validation": copy.deepcopy(
                    ctx["experiment"]["revision_validation"]),
                "approvals": copy.deepcopy(ctx["approvals"])}
        restored = decode_snapshot(encode_snapshot(body))
        self.assertEqual(restored["revision"], live["revision"])
        self.assertEqual(restored["revision"]["origin"], "offline-mock")
        self.assertEqual(restored["revision"]["version"], 1)
        self.assertEqual(restored["revision"]["revision"]
                         ["effect_on_h_ack"]["stance"], "supported")
        self.assertEqual(restored["revision_validation"], live["validation"])
        self.assertEqual(restored["approvals"], live["approvals"])
        self.assertEqual(restored["approvals"][0]["decision"], "approve")
        self.assertIs(restored["approvals"][0]["executed"], False)
        self.assertEqual(restored["lifecycle_stage"], "decided")

    def test_snapshot_build_triggers_no_transitions(self):
        ctx = full_lifecycle_ctx(self)
        before = copy.deepcopy(ctx["experiment"])
        build_snapshot(ctx, evidence_manifest(), 1, now())
        self.assertEqual(ctx["experiment"], before)

    def test_pre_extension_body_rejected(self):
        ctx = full_lifecycle_ctx(self)
        body = build_snapshot(ctx, evidence_manifest(), 1, now())
        for key in ("revision", "revision_validation", "approvals"):
            slim = {k: v for k, v in body.items() if k != key}
            with self.assertRaises(SnapshotError) as cm:
                decode_snapshot(encode_snapshot(slim))
            self.assertEqual(cm.exception.code, "bad-schema",
                             msg=f"missing {key}")

    def test_unknown_schema_rejected(self):
        with self.assertRaises(SnapshotError):
            decode_snapshot(b'{"schema":"MissionSnapshotV9",'
                            b'"snapshot_sha256":"' + b"0" * 64 + b'"}')

    def test_tampered_bytes_rejected(self):
        ctx = new_context()
        raw = bytearray(encode_snapshot(
            build_snapshot(ctx, evidence_manifest(), 1, now())))
        raw[60] ^= 0x01
        with self.assertRaises(SnapshotError):
            decode_snapshot(bytes(raw))

    def test_revision_bound_to_wrong_hypothesis_rejected(self):
        ctx = full_lifecycle_ctx(self)
        body = build_snapshot(ctx, evidence_manifest(), 1, now())
        body["revision"]["revision"]["original_prediction"][
            "hypothesis_id"] = "H-QUEUE"
        with self.assertRaises(SnapshotError) as cm:
            decode_snapshot(encode_snapshot(body))
        self.assertEqual(cm.exception.code, "bad-binding")

    def test_revision_without_prediction_rejected(self):
        ctx = full_lifecycle_ctx(self)
        body = build_snapshot(ctx, evidence_manifest(), 1, now())
        body["prediction"] = None
        with self.assertRaises(SnapshotError) as cm:
            decode_snapshot(encode_snapshot(body))
        self.assertEqual(cm.exception.code, "gated")

    def test_validation_without_revision_rejected(self):
        ctx = full_lifecycle_ctx(self)
        body = build_snapshot(ctx, evidence_manifest(), 1, now())
        body["revision"] = None
        with self.assertRaises(SnapshotError) as cm:
            decode_snapshot(encode_snapshot(body))
        self.assertEqual(cm.exception.code, "gated")

    def test_executed_validation_rejected(self):
        ctx = full_lifecycle_ctx(self)
        body = build_snapshot(ctx, evidence_manifest(), 1, now())
        body["revision_validation"]["executed"] = True
        with self.assertRaises(SnapshotError):
            decode_snapshot(encode_snapshot(body))

    def test_executed_approval_rejected(self):
        ctx = full_lifecycle_ctx(self)
        body = build_snapshot(ctx, evidence_manifest(), 1, now())
        body["approvals"][0]["executed"] = True
        with self.assertRaises(SnapshotError):
            decode_snapshot(encode_snapshot(body))


class PointerContractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name)
        self.ctx = new_context()
        self.run = self.ctx["mission"]["mission_run_id"]
        commit_snapshot(self.store, self.run,
                        build_snapshot(self.ctx, evidence_manifest(), 1,
                                       now()), 0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_resolve_round_trip(self):
        record = active_run.write_pointer(self.store, self.run, 1)
        self.assertEqual(record["pointer_revision"], 1)
        resolved = active_run.resolve_active(self.store)
        self.assertEqual(resolved["state"], "restored")
        self.assertEqual(resolved["snapshot"]["snapshot_revision"], 1)
        self.assertEqual(resolved["pointer"], record)

    def test_pointer_revision_increments(self):
        active_run.write_pointer(self.store, self.run, 1)
        commit_snapshot(self.store, self.run,
                        build_snapshot(self.ctx, evidence_manifest(), 2,
                                       now()), 1)
        record = active_run.write_pointer(self.store, self.run, 2)
        self.assertEqual(record["pointer_revision"], 2)

    def test_uncommitted_selection_refused(self):
        with self.assertRaises(PointerError) as cm:
            active_run.write_pointer(self.store, self.run, 2)
        self.assertEqual(cm.exception.code, "revision-mismatch")
        with self.assertRaises(PointerError) as cm:
            active_run.write_pointer(self.store, "mr-" + "0" * 16, 1)
        self.assertEqual(cm.exception.code, "no-snapshot")

    def test_stale_pointer_writer_aborts(self):
        active_run.write_pointer(self.store, self.run, 1)
        commit_snapshot(self.store, self.run,
                        build_snapshot(self.ctx, evidence_manifest(), 2,
                                       now()), 1)
        active_run.write_pointer(self.store, self.run, 2)
        with self.assertRaises(PointerError) as cm:
            active_run.write_pointer(self.store, self.run, 1,
                                     expected_pointer_revision=1)
        self.assertEqual(cm.exception.code, "stale-pointer")
        self.assertEqual(active_run.resolve_active(self.store)
                         ["snapshot"]["snapshot_revision"], 2)

    def test_corrupt_pointer_state(self):
        active_run.write_pointer(self.store, self.run, 1)
        (self.store / "active-run.json").write_bytes(b"not json{")
        with self.assertRaises(PointerError) as cm:
            active_run.resolve_active(self.store)
        self.assertEqual(cm.exception.code, "pointer-corrupt")
        # Snapshots untouched: explicit load still works.
        loaded = active_run.load_committed(self.store, self.run)
        self.assertEqual(loaded["state"], "unpointed")

    def test_symlink_pointer_refused(self):
        target = self.store / "real-pointer.json"
        target.write_text("{}")
        link = self.store / "active-run.json"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("symlinks unsupported here")
        with self.assertRaises(PointerError) as cm:
            active_run.read_pointer(self.store)
        self.assertEqual(cm.exception.code, "pointer-corrupt")

    def test_malformed_identity_refused(self):
        for bad in ("../escape", "mr-XYZ", "", None):
            with self.assertRaises(PointerError):
                active_run.write_pointer(self.store, bad, 1)

    def test_unsupported_pointer_version(self):
        (self.store / "active-run.json").write_text(json.dumps({
            "schema": "ActiveRunPointerV9", "mission_run_id": self.run,
            "snapshot_revision": 1, "pointer_revision": 1}))
        with self.assertRaises(PointerError) as cm:
            active_run.read_pointer(self.store)
        self.assertEqual(cm.exception.code, "unsupported-pointer")

    def test_identity_mismatch_never_restores(self):
        other = new_context()["mission"]["mission_run_id"]
        (self.store / "active-run.json").write_text(json.dumps({
            "schema": "ActiveRunPointerV1", "mission_run_id": other,
            "snapshot_revision": 1, "pointer_revision": 1}))
        with self.assertRaises(PointerError) as cm:
            active_run.resolve_active(self.store)
        self.assertIn(cm.exception.code, ("no-snapshot", "identity-mismatch"))

    def test_missing_store_and_pointer(self):
        with self.assertRaises(PointerError) as cm:
            active_run.read_pointer(self.store / "absent-dir")
        self.assertEqual(cm.exception.code, "no-store")
        with self.assertRaises(PointerError) as cm:
            active_run.resolve_active(self.store)
        self.assertEqual(cm.exception.code, "no-pointer")


class CrashMatrixTest(unittest.TestCase):
    """Deterministic simulated crashes (not physical power loss)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name)
        self.ctx = new_context()
        self.run = self.ctx["mission"]["mission_run_id"]

    def tearDown(self):
        self.tmp.cleanup()

    def commit_rev(self, rev, expected):
        return commit_snapshot(
            self.store, self.run,
            build_snapshot(self.ctx, evidence_manifest(), rev, now()),
            expected)

    def test_crash_before_any_write(self):
        with self.assertRaises(PointerError) as cm:
            active_run.resolve_active(self.store)
        self.assertEqual(cm.exception.code, "no-pointer")

    def test_crash_during_temp_snapshot_write(self):
        (self.store / f"mission-{self.run}.json.tmp").write_bytes(b"partial")
        with self.assertRaises(PointerError) as cm:
            active_run.resolve_active(self.store)
        self.assertEqual(cm.exception.code, "no-pointer")

    def test_crash_after_replace_before_pointer(self):
        self.commit_rev(1, 0)
        active_run.write_pointer(self.store, self.run, 1)
        self.commit_rev(2, 1)  # committed but never selected: crash point
        resolved = active_run.resolve_active(self.store)
        self.assertEqual(resolved["state"], "restored")
        self.assertEqual(resolved["snapshot"]["snapshot_revision"], 1)
        # The newer unselected generation is flagged, never restored.
        self.assertEqual(resolved["quarantined"], 2)

    def test_mismatched_prev_is_not_honored(self):
        self.commit_rev(1, 0)
        active_run.write_pointer(self.store, self.run, 1)
        self.commit_rev(2, 1)
        prev = self.store / f"mission-{self.run}.json.prev"
        prev.write_bytes(b"corrupt{")
        with self.assertRaises(PointerError) as cm:
            active_run.resolve_active(self.store)
        self.assertEqual(cm.exception.code, "revision-mismatch")

    def test_crash_during_pointer_update(self):
        self.commit_rev(1, 0)
        active_run.write_pointer(self.store, self.run, 1)
        (self.store / "active-run.json.tmp").write_bytes(b"partial")
        resolved = active_run.resolve_active(self.store)
        self.assertEqual(resolved["snapshot"]["snapshot_revision"], 1)

    def test_crash_after_pointer_replace(self):
        self.commit_rev(1, 0)
        self.commit_rev(2, 1)
        active_run.write_pointer(self.store, self.run, 2)
        resolved = active_run.resolve_active(self.store)
        self.assertEqual(resolved["snapshot"]["snapshot_revision"], 2)

    def test_snapshot_corruption_requires_operator(self):
        self.commit_rev(1, 0)
        active_run.write_pointer(self.store, self.run, 1)
        (self.store / f"mission-{self.run}.json").write_bytes(b"corrupt{")
        with self.assertRaises(PointerError) as cm:
            active_run.resolve_active(self.store)
        self.assertEqual(cm.exception.code, "snapshot-invalid")

    def test_valid_snapshots_without_pointer(self):
        self.commit_rev(1, 0)
        with self.assertRaises(PointerError) as cm:
            active_run.resolve_active(self.store)
        self.assertEqual(cm.exception.code, "no-pointer")
        loaded = active_run.load_committed(self.store, self.run)
        self.assertEqual(loaded["state"], "unpointed")


class OperatorLanguageTest(unittest.TestCase):
    def test_every_state_has_plain_language(self):
        for code in ("no-pointer", "pointer-corrupt", "unsupported-pointer",
                     "no-snapshot", "revision-mismatch", "identity-mismatch",
                     "stale-pointer", "no-store", "snapshot-invalid"):
            message = active_run.pointer_state_message(code)
            self.assertTrue(message)
            if code not in ("no-pointer", "no-snapshot", "no-store",
                            "stale-pointer"):
                self.assertIn("Recovery required", message)
        self.assertIn("Save failed",
                      active_run.pointer_state_message("stale-pointer"))
        for code in ("no-pointer", "no-snapshot", "no-store",
                     "stale-pointer"):
            self.assertNotIn("restored", active_run.pointer_state_message(
                code).lower())


class SecurityRegressionTest(unittest.TestCase):
    def test_server_does_not_import_pointer(self):
        src = (ROOT / "backend" / "server.py").read_text()
        self.assertNotIn("active_run", src)
        for route in ("/api/snapshot", "/api/pointer", "/api/active"):
            self.assertNotIn(route, src)

    def test_pointer_module_is_offline(self):
        import re
        src = (ROOT / "backend" / "active_run.py").read_text()
        imported = {name.split(".")[0] for name in re.findall(
            r"^\s*(?:import|from)\s+(\S+)", src, re.M)}
        for token in ("meta_adapter", "socket", "subprocess", "urllib",
                      "http", "ssl", "receipt", "chaos_simulation",
                      "chaos_evaluation", "chaos_recovery", "server"):
            self.assertNotIn(token, imported, msg=token)
        for token in ("MODEL_API_KEY", "Popen", "check_output",
                      "os.system"):
            self.assertNotIn(token, src, msg=token)

    def test_fixtures_untouched(self):
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted((ROOT / "fixtures" / "case-001").iterdir())
                  if p.is_file()}
        full_lifecycle_ctx(self)
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted((ROOT / "fixtures" / "case-001").iterdir())
                 if p.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
