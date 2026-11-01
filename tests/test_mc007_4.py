"""MC-007.4: final persistence acceptance tests.

Offline only, temporary store dirs. Covers acceptance conditions not
already proven in MC-007.2/MC-007.3 suites.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from backend.active_run import resolve_active
from backend.mission_snapshot import build_snapshot, encode_snapshot
from backend.mission_store import commit_snapshot
from backend.persistence import boot_context
from backend.receipt import evidence_manifest
from backend.server import ROOT, handle_request


def call(ctx, method, target, body=None):
    raw = None if body is None else json.dumps(body).encode("utf-8")
    return handle_request(method, target, raw, ctx)


class GetAuditIdempotenceTest(unittest.TestCase):
    def test_repeated_audit_gets_commit_once(self):
        tmp = tempfile.TemporaryDirectory()
        store = Path(tmp.name) / "store"
        ctx, status, _ = boot_context(ROOT, store)
        self.assertEqual(status, "fresh")
        call(ctx, "POST", "/api/mission/diagnostic",
             {"choice": "timestamp-audit"})
        revs = set()
        for _ in range(3):
            status, payload, _ = call(
                ctx, "GET", "/api/mission/diagnostic/result")
            self.assertEqual(status, 200)
            revs.add(ctx["_snapshot_revision"])
        self.assertTrue(ctx["mission"]["audit_viewed"])
        # One commit for the flip; refreshes change nothing.
        self.assertEqual(ctx["_snapshot_revision"], 2)
        self.assertEqual(revs, {2})
        tmp.cleanup()


class ProviderFreeAcceptanceTest(unittest.TestCase):
    def test_boot_reads_and_recovery_make_zero_provider_calls(self):
        import shutil

        import backend.server as server_mod

        real = server_mod.MetaModelAdapter
        server_mod.MetaModelAdapter = lambda: (_ for _ in ()).throw(
            AssertionError("provider must not be called"))
        try:
            tmp = tempfile.TemporaryDirectory()
            store = Path(tmp.name) / "store"
            ctx, _, _ = boot_context(ROOT, store)
            call(ctx, "POST", "/api/mission/diagnostic",
                 {"choice": "feed-probe"})
            for _ in range(2):
                for target in ("/api/mission", "/api/experiment"):
                    status, _, _ = call(ctx, "GET", target)
                    self.assertEqual(status, 200)
            ctx2, status, _ = boot_context(ROOT, store)
            self.assertEqual(status, "restored")
            # Report stays correctly gated pre-assessment after restore.
            status, _, _ = call(ctx2, "GET", "/api/mission/report")
            self.assertEqual(status, 409)
            broken = Path(tmp.name) / "broken"
            shutil.copytree(store, broken)
            (broken / "active-run.json").write_bytes(b"junk")
            _, status, message = boot_context(ROOT, broken)
            self.assertEqual(status, "abort")
            self.assertIn("Recovery required", message)
            tmp.cleanup()
        finally:
            server_mod.MetaModelAdapter = real


class QuarantineAndVersionTest(unittest.TestCase):
    def test_quarantine_flag_names_newer_revision(self):
        tmp = tempfile.TemporaryDirectory()
        store = Path(tmp.name) / "store"
        ctx, _, _ = boot_context(ROOT, store)
        run = ctx["mission"]["mission_run_id"]
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        from backend.mission_store import commit_snapshot as commit

        body = build_snapshot(ctx, evidence_manifest(ROOT), 2, "t")
        commit(store, run, body, 1)  # committed, never pointed
        resolved = resolve_active(store)
        self.assertEqual(resolved["state"], "restored")
        self.assertEqual(resolved["snapshot"]["snapshot_revision"], 1)
        self.assertEqual(resolved["quarantined"], 2)
        tmp.cleanup()

    def test_unsupported_snapshot_schema_aborts_boot(self):
        tmp = tempfile.TemporaryDirectory()
        store = Path(tmp.name) / "store"
        ctx, _, _ = boot_context(ROOT, store)
        run = ctx["mission"]["mission_run_id"]
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        main = next(store.glob("mission-*.json"))
        body = json.loads(main.read_bytes())
        body["schema"] = "MissionSnapshotV9"
        main.write_bytes(encode_snapshot(body))
        _, status, message = boot_context(ROOT, store)
        self.assertEqual(status, "abort")
        self.assertIn("Recovery required", message)
        tmp.cleanup()

    def test_boot_never_serves_unresolved_state(self):
        tmp = tempfile.TemporaryDirectory()
        store = Path(tmp.name) / "store"
        store.mkdir()
        (store / "active-run.json").write_text(json.dumps({
            "schema": "ActiveRunPointerV1",
            "mission_run_id": "mr-" + "1" * 16,
            "snapshot_revision": 1, "pointer_revision": 1}))
        ctx, status, message = boot_context(ROOT, store)
        self.assertEqual(status, "abort")
        self.assertEqual(ctx, {})
        self.assertTrue(message)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
