"""CP-002: audit logging and backup/restore acceptance.

Offline only, temporary directories. No provider calls, no receipt
changes, no server route changes, no fixture mutation.
"""

import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from backend import audit_log, backup
from backend.audit_log import AuditError
from backend.backup import BackupError
from backend.persistence import boot_context
from backend.server import ROOT, handle_request

PREDICTION = {
    "hypothesis_id": "H-ACK", "expected_finding": "ack-found",
    "expected_observation": "Source holds a case-003 ack missing.",
    "criteria": "ack-found supports H-ACK.",
    "refs": ["case-003", "events.csv"],
}


def call(ctx, method, target, body=None):
    raw = None if body is None else json.dumps(body).encode("utf-8")
    return handle_request(method, target, raw, ctx)


def booted(case, store):
    ctx, status, _ = boot_context(ROOT, store)
    case.assertEqual(status, "fresh")
    return ctx


class AuditLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = str(Path(self.tmp.name) / "store")
        os.environ.pop("FDE_MISSION_STORE", None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_accepted_and_rejected_events_recorded(self):
        ctx = booted(self, self.store)
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        status, _, _ = call(ctx, "POST", "/api/experiment/reveal", None)
        self.assertEqual(status, 409)
        records = audit_log.read_all(self.store)
        accepted = [r for r in records if r["outcome"] == "accepted"]
        rejected = [r for r in records if r["outcome"] == "rejected"]
        self.assertTrue(any(r["event"] == "POST /api/mission/diagnostic"
                            and r["snapshot_revision"] == 1
                            for r in accepted))
        self.assertTrue(any(r["event"] == "POST /api/experiment/reveal"
                            and r["code"] == "too-early"
                            for r in rejected))
        self.assertEqual(records[0]["mission_run_id"],
                         ctx["mission"]["mission_run_id"])

    def test_no_secrets_or_payloads_logged(self):
        ctx = booted(self, self.store)
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        call(ctx, "POST", "/api/experiment/predict", PREDICTION)
        call(ctx, "POST", "/api/mission/intervention",
             {"decision": "approve", "note": "s3cr3t-note-marker",
              "proposal_id": "x", "proposal_version": "v1"})
        blob = Path(self.store, "audit.log").read_text()
        for token in ("s3cr3t-note-marker", "MODEL_API_KEY", "observations",
                      "investigation", "rationale", "Authorization"):
            self.assertNotIn(token, blob)
        allowed = {"schema", "at", "event", "outcome", "mission_run_id",
                   "snapshot_revision", "category", "code"}
        for line in blob.splitlines():
            self.assertLessEqual(set(json.loads(line)), allowed)
        mode = stat.S_IMODE(Path(self.store, "audit.log").stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_audit_failure_degrades_without_false_ack(self):
        ctx = booted(self, self.store)
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        log = Path(self.store, "audit.log")
        log.unlink()
        log.mkdir()  # audit appends now fail: path is a directory
        status, _, _ = call(ctx, "POST", "/api/experiment/predict",
                            PREDICTION)
        # Durable truth: committed. Acknowledged as accepted, but the
        # missing audit record forces degraded mode instead of silence.
        self.assertEqual(status, 200)
        self.assertTrue(ctx["_persistence_degraded"])
        self.assertIsNotNone(ctx["experiment"]["prediction"])
        status, payload, _ = call(ctx, "POST", "/api/experiment/reveal",
                                  None)
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "persistence-degraded")

    def test_reject_path_audit_failure_never_breaks_rejection(self):
        ctx = booted(self, self.store)
        log = Path(self.store)
        log.mkdir()
        (log / "audit.log").mkdir()
        status, payload, _ = call(ctx, "POST", "/api/experiment/reveal",
                                  None)
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "too-early")


class BackupRestoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = str(Path(self.tmp.name) / "store")
        os.environ.pop("FDE_MISSION_STORE", None)

    def tearDown(self):
        self.tmp.cleanup()

    def drive(self, ctx):
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        call(ctx, "POST", "/api/experiment/predict", PREDICTION)
        return ctx["mission"]["mission_run_id"]

    def test_backup_restore_round_trip(self):
        ctx = booted(self, self.store)
        run = self.drive(ctx)
        dest = str(Path(self.tmp.name) / "backups")
        manifest = backup.create_backup(self.store, dest, label="test")
        self.assertEqual(manifest["mission_run_id"], run)
        self.assertEqual(manifest["snapshot_revision"], 2)
        backup_dir = next(Path(dest).iterdir())
        self.assertEqual(backup.inspect_backup(str(backup_dir)), manifest)
        restored = str(Path(self.tmp.name) / "restored")
        backup.restore_backup(str(backup_dir), restored)
        ctx2, status, _ = boot_context(ROOT, restored)
        self.assertEqual(status, "restored")
        self.assertEqual(ctx2["mission"]["mission_run_id"], run)
        self.assertEqual(ctx2["experiment"]["status"], "prediction locked")
        # Source store untouched by backup and restore.
        ctx3, status, _ = boot_context(ROOT, self.store)
        self.assertEqual(status, "restored")

    def test_corrupt_backup_rejected(self):
        ctx = booted(self, self.store)
        self.drive(ctx)
        dest = str(Path(self.tmp.name) / "backups")
        backup.create_backup(self.store, dest)
        backup_dir = next(Path(dest).iterdir())
        (backup_dir / "active-run.json").write_bytes(b"corrupt{")
        with self.assertRaises(BackupError) as cm:
            backup.inspect_backup(str(backup_dir))
        self.assertEqual(cm.exception.code, "corrupt")
        with self.assertRaises(BackupError):
            backup.restore_backup(str(backup_dir),
                                  str(Path(self.tmp.name) / "r2"))

    def test_pointer_snapshot_mismatch_rejected(self):
        ctx = booted(self, self.store)
        self.drive(ctx)
        dest = str(Path(self.tmp.name) / "backups")
        backup.create_backup(self.store, dest)
        backup_dir = next(Path(dest).iterdir())
        # Swap in a valid snapshot from a different run.
        other = str(Path(self.tmp.name) / "other")
        ctx2 = booted(self, other)
        self.drive(ctx2)
        foreign = next(Path(other).glob("mission-*.json"))
        victim = next(backup_dir.glob("mission-*.json"))
        victim.write_bytes(foreign.read_bytes())
        with self.assertRaises(BackupError) as cm:
            backup.inspect_backup(str(backup_dir))
        self.assertIn(cm.exception.code, ("corrupt", "identity-mismatch"))

    def test_restore_refuses_nonempty_destination(self):
        ctx = booted(self, self.store)
        self.drive(ctx)
        dest = str(Path(self.tmp.name) / "backups")
        backup.create_backup(self.store, dest)
        backup_dir = next(Path(dest).iterdir())
        with self.assertRaises(BackupError) as cm:
            backup.restore_backup(str(backup_dir), self.store)
        self.assertEqual(cm.exception.code, "dest-not-empty")

    def test_restore_replays_nothing(self):
        ctx = booted(self, self.store)
        run = self.drive(ctx)
        dest = str(Path(self.tmp.name) / "backups")
        backup.create_backup(self.store, dest)
        backup_dir = next(Path(dest).iterdir())
        restored = str(Path(self.tmp.name) / "restored")
        backup.restore_backup(str(backup_dir), restored)
        before = sorted(p.name for p in Path(restored).iterdir())
        ctx2, _, _ = boot_context(ROOT, restored)
        status, _, _ = call(ctx2, "POST", "/api/experiment/predict",
                            PREDICTION)
        self.assertEqual(status, 409)  # already locked, not duplicated
        after = sorted(p.name for p in Path(restored).iterdir())
        # Only the audit log gains the rejected-event record.
        self.assertEqual(set(after) - set(before), set())

    def test_no_receipt_changes_no_provider(self):
        import backend.server as server_mod

        before = {}
        for base in ("evaluator-private",):
            for path in sorted((ROOT / base).rglob("*")):
                if path.is_file():
                    before[str(path)] = hashlib.sha256(
                        path.read_bytes()).hexdigest()
        real = server_mod.MetaModelAdapter
        server_mod.MetaModelAdapter = lambda: (_ for _ in ()).throw(
            AssertionError("provider must not be called"))
        try:
            ctx = booted(self, self.store)
            self.drive(ctx)
            dest = str(Path(self.tmp.name) / "backups")
            manifest = backup.create_backup(self.store, dest)
            backup.restore_backup(
                str(next(Path(dest).iterdir())),
                str(Path(self.tmp.name) / "restored"))
            self.assertTrue(manifest["files"])
        finally:
            server_mod.MetaModelAdapter = real
        after = {}
        for base in ("evaluator-private",):
            for path in sorted((ROOT / base).rglob("*")):
                if path.is_file():
                    after[str(path)] = hashlib.sha256(
                        path.read_bytes()).hexdigest()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
