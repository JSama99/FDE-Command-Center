"""MC-004f: atomic MissionSnapshotV1 storage tests.

Real production codec (backend.mission_snapshot) plus the real store
(backend.mission_store). All storage confined to per-test temp dirs;
faults are injected or simulated — no real application state touched,
no network, no provider calls.
"""

import json
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from backend.experiment import build_registry, lock_prediction
from backend.mission import choose_diagnostic
from backend.mission_snapshot import SnapshotError, build_snapshot
from backend.mission_store import (StoreError, commit_snapshot,
                                   inspect_snapshot_status, load_snapshot)
from backend.receipt import evidence_manifest
from backend.server import new_context

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-10-29T00:00:00+00:00"
PREDICTION = {
    "hypothesis_id": "H-ACK",
    "expected_finding": "ack-found",
    "expected_observation": "Source log holds a case-003 ack missing from the feed.",
    "criteria": "ack-found supports H-ACK; no-ack supports H-QUEUE.",
    "refs": ["case-003", "events.csv"],
}
RUN = "mr-" + "a" * 16


def fresh_ctx():
    return new_context()


def locked_ctx():
    ctx = new_context()
    choose_diagnostic(ctx, "feed-probe")
    lock_prediction(ctx["experiment"], dict(PREDICTION),
                    build_registry(ROOT), 1700000000, origin="human-authored")
    return ctx


def body_for(ctx, revision):
    return build_snapshot(ctx, evidence_manifest(ROOT), revision, NOW)


def main_path(store, run=RUN):
    return Path(store) / f"mission-{run}.json"


class StoreBehaviorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "store"

    def test_missing_status_and_load(self):
        self.assertEqual(inspect_snapshot_status(self.store, RUN),
                         ("missing", "no-snapshot"))
        with self.assertRaises(StoreError) as cm:
            load_snapshot(self.store, RUN)
        self.assertEqual(cm.exception.code, "missing")

    def test_commit_load_round_trip_and_permissions(self):
        body = body_for(fresh_ctx(), 1)
        rev = commit_snapshot(self.store, RUN, body, 0)
        self.assertEqual(rev, 1)
        loaded = load_snapshot(self.store, RUN)
        self.assertEqual(loaded["mission_run_id"], body["mission_run_id"])
        self.assertEqual(inspect_snapshot_status(self.store, RUN),
                         ("ok", "current"))
        self.assertEqual(stat.S_IMODE(self.store.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(main_path(self.store).stat().st_mode),
                         0o600)
        self.assertFalse((Path(self.store) / f"mission-{RUN}.json.tmp").exists())

    def test_run_identity_preserved_across_revisions(self):
        ctx = locked_ctx()
        run = ctx["mission"]["mission_run_id"]
        commit_snapshot(self.store, run, body_for(ctx, 1), 0)
        commit_snapshot(self.store, run, body_for(ctx, 2), 1)
        loaded = load_snapshot(self.store, run)
        self.assertEqual(loaded["mission_run_id"], run)
        self.assertEqual(loaded["prediction"],
                         ctx["experiment"]["prediction"])
        prev = json.loads((Path(self.store) / f"mission-{run}.json.prev").read_text())
        self.assertEqual(prev["snapshot_revision"], 1)

    def test_corrupt_current_never_falls_back(self):
        ctx = locked_ctx()
        run = ctx["mission"]["mission_run_id"]
        commit_snapshot(self.store, run, body_for(ctx, 1), 0)
        commit_snapshot(self.store, run, body_for(ctx, 2), 1)
        main_path(self.store, run).write_text('{"schema": "MissionSnapshotV1", "cut')
        with self.assertRaises(StoreError) as cm:
            load_snapshot(self.store, run)
        self.assertEqual(cm.exception.code, "current-invalid")
        state, _ = inspect_snapshot_status(self.store, run)
        self.assertEqual(state, "recovery-required")

    def test_garbage_previous_generation_ignored(self):
        commit_snapshot(self.store, RUN, body_for(fresh_ctx(), 1), 0)
        (Path(self.store) / f"mission-{RUN}.json.prev").write_text("garbage")
        self.assertEqual(load_snapshot(self.store, RUN)["snapshot_revision"], 1)
        self.assertEqual(inspect_snapshot_status(self.store, RUN),
                         ("ok", "current"))

    def test_stale_revision_rejected_without_write(self):
        commit_snapshot(self.store, RUN, body_for(fresh_ctx(), 1), 0)
        before = main_path(self.store).read_bytes()
        with self.assertRaises(StoreError) as cm:
            commit_snapshot(self.store, RUN, body_for(fresh_ctx(), 1), 0)
        self.assertEqual(cm.exception.code, "stale-revision")
        self.assertEqual(main_path(self.store).read_bytes(), before)

    def test_competing_writers_one_wins(self):
        body = body_for(fresh_ctx(), 1)
        outcomes = []
        barrier = threading.Barrier(8)

        def attempt():
            barrier.wait()
            try:
                commit_snapshot(self.store, RUN, body, 0)
                outcomes.append("won")
            except StoreError as exc:
                outcomes.append(exc.code)

        threads = [threading.Thread(target=attempt) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(outcomes.count("won"), 1)
        self.assertEqual(outcomes.count("stale-revision"), 7)
        self.assertEqual(load_snapshot(self.store, RUN)["snapshot_revision"], 1)

    def test_truncated_tmp_and_interrupted_write(self):
        store = Path(self.tmp.name) / "other"
        store.mkdir(mode=0o700)
        (store / f"mission-{RUN}.json.tmp").write_text('{"partial":')
        self.assertEqual(inspect_snapshot_status(store, RUN),
                         ("missing", "no-snapshot"))
        commit_snapshot(store, RUN, body_for(fresh_ctx(), 1), 0)
        self.assertEqual(inspect_snapshot_status(store, RUN),
                         ("ok", "current"))

    def test_confirm_failure_after_replace_is_explicit(self):
        commit_snapshot(self.store, RUN, body_for(fresh_ctx(), 1), 0)
        calls = []

        real_decode = __import__("backend.mission_snapshot",
                                 fromlist=["decode_snapshot"]).decode_snapshot

        def flaky(raw):
            calls.append(raw)
            if len(calls) >= 3:
                raise SnapshotError("injected confirm fault", "confirm-fault")
            return real_decode(raw)

        with mock.patch("backend.mission_store.decode_snapshot",
                        side_effect=flaky):
            with self.assertRaises(StoreError) as cm:
                commit_snapshot(self.store, RUN, body_for(fresh_ctx(), 2), 1)
        self.assertEqual(cm.exception.code, "confirm-failed")

    def test_store_path_is_file_rejected(self):
        block = Path(self.tmp.name) / "block"
        block.write_text("x")
        with self.assertRaises(StoreError):
            commit_snapshot(block, RUN, body_for(fresh_ctx(), 1), 0)

    def test_run_id_traversal_rejected(self):
        for bad in ("../evil", "mr-short", "", "mr-" + "Z" * 16):
            with self.assertRaises(StoreError, msg=str(bad)) as cm:
                load_snapshot(self.store, bad)
            self.assertEqual(cm.exception.code, "bad-identity")

    def test_explicit_modes_survive_permissive_umask(self):
        old = os.umask(0o022)
        try:
            commit_snapshot(self.store, RUN, body_for(fresh_ctx(), 1), 0)
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(main_path(self.store).stat().st_mode),
                         0o600)
        self.assertEqual(stat.S_IMODE(self.store.stat().st_mode), 0o700)

    def test_malformed_manifest_rejected_before_write(self):
        body = body_for(fresh_ctx(), 1)
        body["source_manifest"] = {"fixtures/case-001/events.csv": "short"}
        with self.assertRaises(StoreError) as cm:
            commit_snapshot(self.store, RUN, body, 0)
        self.assertEqual(cm.exception.code, "invalid-candidate")
        self.assertEqual(inspect_snapshot_status(self.store, RUN),
                         ("missing", "no-snapshot"))

    def test_invalid_candidate_never_published(self):
        body = body_for(fresh_ctx(), 1)
        body["lifecycle_stage"] = "assessed"
        with self.assertRaises(StoreError):
            commit_snapshot(self.store, RUN, body, 0)
        self.assertFalse(main_path(self.store).exists())


if __name__ == "__main__":
    unittest.main()
