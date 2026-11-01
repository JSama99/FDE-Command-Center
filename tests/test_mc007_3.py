"""MC-007.3: durable persistence integration tests.

Booted server contexts (explicit temporary store dirs) through the real
handle_request path. No real store touched, no provider calls, no
receipt linkage, no fixture mutation.
"""

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from backend.active_run import read_pointer
from backend.persistence import boot_context
from backend.server import ROOT, handle_request, new_context

PREDICTION = {
    "hypothesis_id": "H-ACK",
    "expected_finding": "ack-found",
    "expected_observation": "Source log holds a case-003 ack missing from the feed.",
    "criteria": "ack-found supports H-ACK; no-ack supports H-QUEUE.",
    "refs": ["case-003", "events.csv"],
}


def call(ctx, method, target, body=None, transport=None):
    raw = None if body is None else json.dumps(body).encode("utf-8")
    return handle_request(method, target, raw, ctx, transport)


def boot_fresh(case, store):
    ctx, status, message = boot_context(ROOT, store)
    case.assertEqual(status, "fresh", msg=message)
    return ctx


def snapshot_files(store):
    return sorted(p.name for p in Path(store).iterdir()
                  if p.is_file() and p.name.startswith("mission-")
                  and not p.name.endswith(".tmp"))


class StartupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"
        os.environ.pop("FDE_MISSION_STORE", None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fresh_startup_creates_nothing(self):
        ctx = boot_fresh(self, self.store)
        self.assertNotIn("receipt", json.dumps(ctx["mission"]).lower())
        self.assertFalse(self.store.exists())
        self.assertEqual(ctx["_snapshot_revision"], 0)

    def test_accepted_transition_commits_and_points(self):
        ctx = boot_fresh(self, self.store)
        status, _, _ = call(ctx, "POST", "/api/mission/diagnostic",
                            {"choice": "feed-probe"})
        self.assertEqual(status, 200)
        self.assertEqual(ctx["_snapshot_revision"], 1)
        pointer = read_pointer(self.store)
        self.assertEqual(pointer["snapshot_revision"], 1)
        self.assertEqual(pointer["mission_run_id"],
                         ctx["mission"]["mission_run_id"])
        self.assertTrue(snapshot_files(self.store))

    def test_restart_restores_exact_run(self):
        ctx = boot_fresh(self, self.store)
        run = ctx["mission"]["mission_run_id"]
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        call(ctx, "POST", "/api/experiment/predict", PREDICTION)
        ctx2, status, _ = boot_context(ROOT, self.store)
        self.assertEqual(status, "restored")
        self.assertEqual(ctx2["mission"]["mission_run_id"], run)
        self.assertEqual(ctx2["mission"]["diagnostic"], "feed-probe")
        self.assertEqual(ctx2["experiment"]["prediction"],
                         ctx["experiment"]["prediction"])
        self.assertEqual(ctx2["experiment"]["status"], "prediction locked")

    def test_restart_restores_revision_and_approvals(self):
        ctx = boot_fresh(self, self.store)
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        call(ctx, "POST", "/api/experiment/predict", PREDICTION)
        call(ctx, "POST", "/api/experiment/reveal", None)
        call(ctx, "POST", "/api/experiment/assess", None)
        status, _, _ = call(ctx, "POST", "/api/revision/generate",
                            {"mode": "mock"})
        self.assertEqual(status, 200)
        call(ctx, "POST", "/api/revision/approve",
             {"decision": "approve", "note": "Evidence-bound."})
        call(ctx, "POST", "/api/approval",
             {"decision": "approve", "note": "Reviewed."})
        ctx2, status, _ = boot_context(ROOT, self.store)
        self.assertEqual(status, "restored")
        self.assertEqual(ctx2["experiment"]["revision"],
                         ctx["experiment"]["revision"])
        self.assertEqual(ctx2["experiment"]["revision_validation"],
                         ctx["experiment"]["revision_validation"])
        self.assertEqual(ctx2["approvals"], ctx["approvals"])

    def test_restart_preserves_proposal_and_decision(self):
        ctx = boot_fresh(self, self.store)
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        call(ctx, "POST", "/api/experiment/predict", PREDICTION)
        call(ctx, "POST", "/api/experiment/reveal", None)
        call(ctx, "POST", "/api/experiment/assess", None)
        _, proposal, _ = call(ctx, "GET", "/api/mission/proposal")
        call(ctx, "POST", "/api/mission/intervention", {
            "decision": "approve", "note": "Smallest reversible step.",
            "proposal_id": proposal["proposal_id"],
            "proposal_version": proposal["version"]})
        ctx2, status, _ = boot_context(ROOT, self.store)
        self.assertEqual(status, "restored")
        _, proposal2, _ = call(ctx2, "GET", "/api/mission/proposal")
        self.assertEqual(proposal2["proposal_id"], proposal["proposal_id"])
        self.assertEqual(ctx2["mission"]["intervention"]["note"],
                         "Smallest reversible step.")
        _, report, _ = call(ctx2, "GET", "/api/mission/report")
        self.assertNotIn('"executed": true', json.dumps(report))

    def test_corrupt_snapshot_aborts_startup(self):
        ctx = boot_fresh(self, self.store)
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        main = next(Path(self.store).glob("mission-*.json"))
        main.write_bytes(b"corrupt{")
        ctx2, status, message = boot_context(ROOT, self.store)
        self.assertEqual(status, "abort")
        self.assertIn("Recovery required", message)
        self.assertEqual(ctx2, {})

    def test_corrupt_pointer_aborts_startup(self):
        ctx = boot_fresh(self, self.store)
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        (Path(self.store) / "active-run.json").write_bytes(b"nope")
        _, status, message = boot_context(ROOT, self.store)
        self.assertEqual(status, "abort")
        self.assertIn("Recovery required", message)

    def test_manifest_drift_aborts_startup(self):
        import backend.persistence as persist

        ctx = boot_fresh(self, self.store)
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        real = persist.evidence_manifest
        try:
            persist.evidence_manifest = lambda base: {"drifted": "x"}
            _, status, message = boot_context(ROOT, self.store)
        finally:
            persist.evidence_manifest = real
        self.assertEqual(status, "abort")
        self.assertIn("source evidence changed", message)


class CommitSemanticsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"
        os.environ.pop("FDE_MISSION_STORE", None)
        self.ctx = boot_fresh(self, self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_rejected_transition_writes_nothing(self):
        status, _, _ = call(self.ctx, "POST", "/api/experiment/reveal", None)
        self.assertEqual(status, 409)
        self.assertFalse(self.store.exists())
        self.assertEqual(self.ctx["_snapshot_revision"], 0)

    def test_retry_after_commit_does_not_duplicate(self):
        call(self.ctx, "POST", "/api/mission/diagnostic",
             {"choice": "feed-probe"})
        status, _, _ = call(self.ctx, "POST", "/api/experiment/predict",
                            PREDICTION)
        self.assertEqual(status, 200)
        rev = self.ctx["_snapshot_revision"]
        status, _, _ = call(self.ctx, "POST", "/api/experiment/predict",
                            PREDICTION)
        self.assertEqual(status, 409)
        self.assertEqual(self.ctx["_snapshot_revision"], rev)
        self.assertEqual(read_pointer(self.store)["pointer_revision"], rev)

    def test_concurrent_context_stale_rejected(self):
        twin = copy.deepcopy(self.ctx)
        call(self.ctx, "POST", "/api/mission/diagnostic",
             {"choice": "feed-probe"})
        self.assertEqual(self.ctx["_snapshot_revision"], 1)
        status, payload, _ = call(twin, "POST", "/api/mission/diagnostic",
                                  {"choice": "feed-probe"})
        self.assertEqual(status, 500)
        self.assertEqual(payload["error"], "persistence-failed")
        self.assertIsNone(twin["mission"]["diagnostic"])
        self.assertEqual(twin["_snapshot_revision"], 0)

    def test_unwritable_store_no_ack(self):
        blocker = Path(self.tmp.name) / "file-store"
        blocker.write_text("not a directory")
        ctx, status, _ = boot_context(ROOT, blocker)
        self.assertEqual(status, "fresh")
        # fresh_context records the path; first commit must fail, not ack.
        status, payload, _ = call(ctx, "POST", "/api/mission/diagnostic",
                                  {"choice": "feed-probe"})
        self.assertEqual(status, 500)
        self.assertEqual(payload["error"], "persistence-failed")
        self.assertIsNone(ctx["mission"]["diagnostic"])
        self.assertEqual(ctx["_snapshot_revision"], 0)

    def test_pointer_failure_degrades_without_ack(self):
        call(self.ctx, "POST", "/api/mission/diagnostic",
             {"choice": "feed-probe"})
        (Path(self.store) / "active-run.json").unlink()
        (Path(self.store) / "active-run.json").mkdir()
        status, payload, _ = call(self.ctx, "POST",
                                  "/api/experiment/predict", PREDICTION)
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "persistence-degraded")
        self.assertIsNone(self.ctx["experiment"]["prediction"])
        # Reads continue; further mutations refused.
        status, _, _ = call(self.ctx, "GET", "/api/mission")
        self.assertEqual(status, 200)
        status, _, _ = call(self.ctx, "POST", "/api/experiment/predict",
                            PREDICTION)
        self.assertEqual(status, 503)

    def test_boot_adopts_proven_successor(self):
        from backend.mission_store import commit_snapshot
        from backend.mission_snapshot import build_snapshot
        from backend.receipt import evidence_manifest

        call(self.ctx, "POST", "/api/mission/diagnostic",
             {"choice": "feed-probe"})
        run = self.ctx["mission"]["mission_run_id"]
        body = build_snapshot(self.ctx, evidence_manifest(ROOT), 2, "t")
        commit_snapshot(self.store, run, body, 1)  # crash before pointing
        ctx2, status, message = boot_context(ROOT, self.store)
        self.assertEqual(status, "restored")
        self.assertIn("adopting", message)
        self.assertEqual(ctx2["_snapshot_revision"], 2)
        self.assertEqual(read_pointer(self.store)["snapshot_revision"], 2)


class BoundaryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"
        os.environ.pop("FDE_MISSION_STORE", None)

    def tearDown(self):
        self.tmp.cleanup()

    def digest_dir(self, *names):
        out = {}
        for name in names:
            for path in sorted((ROOT / name).iterdir()):
                if path.is_file():
                    out[str(path)] = hashlib.sha256(
                        path.read_bytes()).hexdigest()
        return out

    def test_no_receipt_linkage_no_simulation_no_provider(self):
        import backend.server as server_mod

        before_receipts = self.digest_dir("evaluator-private")
        before_chaos = self.digest_dir("fixtures/chaos-lab")
        real_adapter = server_mod.MetaModelAdapter
        server_mod.MetaModelAdapter = lambda: (_ for _ in ()).throw(
            AssertionError("provider must not be called"))
        try:
            ctx = boot_fresh(self, self.store)
            call(ctx, "POST", "/api/mission/diagnostic",
                 {"choice": "feed-probe"})
            call(ctx, "POST", "/api/experiment/predict", PREDICTION)
            call(ctx, "POST", "/api/experiment/reveal", None)
            call(ctx, "POST", "/api/experiment/assess", None)
            call(ctx, "POST", "/api/revision/generate", {"mode": "mock"})
            ctx2, status, _ = boot_context(ROOT, self.store)
            self.assertEqual(status, "restored")
        finally:
            server_mod.MetaModelAdapter = real_adapter
        self.assertEqual(before_receipts, self.digest_dir("evaluator-private"))
        self.assertEqual(before_chaos, self.digest_dir("fixtures/chaos-lab"))
        self.assertNotIn("receipt", json.dumps(ctx2["mission"]).lower())

    def test_routes_and_frontend_compatible(self):
        import re

        ctx = boot_fresh(self, self.store)
        status, _, content_type = call(ctx, "GET", "/control.html")
        self.assertEqual(status, 200)
        self.assertIn("html", content_type)
        routes = set(re.findall(r'path == "([^"]+)" and method == "POST"',
                                (ROOT / "backend" / "server.py").read_text()))
        self.assertNotIn("/api/snapshot", routes)
        files_before = snapshot_files(self.store) if Path(
            self.store).exists() else []
        transport = {"peer": "127.0.0.1",
                     "origin": "http://localhost:8000",
                     "host": "localhost:8000",
                     "local_origins": {"http://localhost:8000"},
                     "local_hosts": {"localhost:8000"}}
        call(ctx, "POST", "/api/chaos/run",
             {"scenario_id": "CHS-ASSIGN-01", "variant": "baseline"},
             transport)
        files_after = snapshot_files(self.store) if Path(
            self.store).exists() else []
        self.assertEqual(files_before, files_after)

    def test_legacy_context_stays_ephemeral(self):
        ctx = new_context()
        self.assertNotIn("_store_dir", ctx)
        status, _, _ = call(ctx, "POST", "/api/mission/diagnostic",
                            {"choice": "feed-probe"})
        self.assertEqual(status, 200)
        self.assertNotIn("_store_dir", ctx)
        self.assertFalse((ROOT / "mission-snapshots").exists())


if __name__ == "__main__":
    unittest.main()
