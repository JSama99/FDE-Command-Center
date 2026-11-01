"""MC-004c: server-minted mission_run_id lifecycle and invariants.

Offline only: handle_request against in-memory contexts, plus fresh
interpreters via subprocess for restart semantics. No provider calls,
no receipts created or modified.
"""

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from backend.mission import MISSION_ID, new_mission_state
from backend.server import handle_request, new_context

try:
    from test_mission_control import exec_frontend
except ModuleNotFoundError:  # invoked as tests.test_mission_run_id
    from tests.test_mission_control import exec_frontend

ROOT = Path(__file__).resolve().parents[1]
RUN_RE = re.compile(r"^mr-[0-9a-f]{16}$")
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


def run_id(ctx):
    status, mission, _ = call(ctx, "GET", "/api/mission")
    assert status == 200
    return mission["mission"]["mission_run_id"]


class RunIdentityTest(unittest.TestCase):
    def test_identifier_present_and_formatted(self):
        ctx = new_context()
        rid = run_id(ctx)
        self.assertRegex(rid, RUN_RE)
        self.assertNotEqual(rid, MISSION_ID)
        self.assertNotIn("case-001", rid)
        self.assertNotIn("EXP-001", rid)

    def test_two_contexts_receive_different_ids(self):
        self.assertNotEqual(run_id(new_context()), run_id(new_context()))

    def test_repeated_get_returns_same_id(self):
        ctx = new_context()
        first = run_id(ctx)
        for _ in range(3):
            self.assertEqual(run_id(ctx), first)

    def test_successful_lifecycle_preserves_id(self):
        ctx = new_context()
        first = run_id(ctx)
        for method, target, body in [
            ("POST", "/api/mission/diagnostic", {"choice": "feed-probe"}),
            ("POST", "/api/experiment/predict", PREDICTION),
            ("POST", "/api/experiment/reveal", None),
            ("POST", "/api/experiment/assess", None),
            ("GET", "/api/mission/proposal", None),
        ]:
            status, _, _ = call(ctx, method, target, body)
            self.assertIn(status, (200,), msg=f"{method} {target}")
            self.assertEqual(run_id(ctx), first)
        status, proposal, _ = call(ctx, "GET", "/api/mission/proposal")
        self.assertEqual(status, 200)
        status, _, _ = call(ctx, "POST", "/api/mission/intervention", {
            "decision": "approve",
            "note": "Feed reconciliation is the smallest reversible next step.",
            "proposal_id": proposal["proposal_id"],
            "proposal_version": proposal["version"],
        })
        self.assertEqual(status, 200)
        status, report, _ = call(ctx, "GET", "/api/mission/report")
        self.assertEqual(status, 200)
        self.assertEqual(run_id(ctx), first)

    def test_rejected_operations_preserve_id(self):
        ctx = new_context()
        first = run_id(ctx)
        status, _, _ = call(ctx, "POST", "/api/experiment/reveal", None)
        self.assertEqual(status, 409)
        status, _, _ = call(ctx, "POST", "/api/experiment/predict",
                             dict(PREDICTION, hypothesis_id="H-NOPE"))
        self.assertEqual(status, 400)
        status, _, _ = call(ctx, "POST", "/api/mission/diagnostic",
                             {"choice": "feed-probe"})
        self.assertEqual(status, 200)
        status, _, _ = call(ctx, "POST", "/api/mission/diagnostic",
                             {"choice": "timestamp-audit"})
        self.assertEqual(status, 409)
        status, _, _ = call(ctx, "POST", "/api/experiment/predict", PREDICTION)
        self.assertEqual(status, 200)
        status, _, _ = call(ctx, "POST", "/api/experiment/predict", PREDICTION)
        self.assertEqual(status, 409)
        self.assertEqual(run_id(ctx), first)

    def test_client_supplied_id_cannot_overwrite(self):
        ctx = new_context()
        first = run_id(ctx)
        for method, target, body in [
            ("POST", "/api/mission/diagnostic",
             {"choice": "feed-probe", "mission_run_id": "mr-forged00000000"}),
            ("POST", "/api/experiment/predict",
             dict(PREDICTION, mission_run_id="mr-forged00000000")),
            ("POST", "/api/mission/intervention",
             {"decision": "approve", "note": "x" * 40,
              "proposal_id": "PROP-004", "proposal_version": "v1",
              "mission_run_id": "mr-forged00000000"}),
        ]:
            call(ctx, method, target, body)
            self.assertEqual(run_id(ctx), first)
        self.assertNotEqual(first, "mr-forged00000000")

    def test_separate_runs_may_share_case(self):
        first, second = new_context(), new_context()
        self.assertNotEqual(run_id(first), run_id(second))
        _, m1, _ = call(first, "GET", "/api/mission")
        _, m2, _ = call(second, "GET", "/api/mission")
        self.assertEqual(m1["mission_id"], m2["mission_id"])

    def test_fresh_interpreters_mint_new_ids(self):
        code = ("from backend.server import new_context;"
                "print(new_context()['mission']['mission_run_id'])")
        ids = set()
        for _ in range(3):
            proc = subprocess.run([sys.executable, "-c", code],
                                  capture_output=True, text=True, timeout=60,
                                  cwd=ROOT)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr[-1000:])
            rid = proc.stdout.strip()
            self.assertRegex(rid, RUN_RE)
            ids.add(rid)
        self.assertEqual(len(ids), 3)

    def test_lifecycle_needs_no_provider(self):
        saved = os.environ.pop("MODEL_API_KEY", None)
        try:
            self.test_successful_lifecycle_preserves_id()
        finally:
            if saved is not None:
                os.environ["MODEL_API_KEY"] = saved

    def test_frontend_tolerates_run_field(self):
        status, mission, _ = call(new_context(), "GET", "/api/mission")
        self.assertEqual(status, 200)
        out = exec_frontend(self, [], mission)
        self.assertIn("run mr-", out["roomContext"])
        self.assertIn(mission["mission"]["mission_run_id"], out["roomContext"])

    def test_no_receipt_linkage_introduced(self):
        status, mission, _ = call(new_context(), "GET", "/api/mission")
        self.assertEqual(status, 200)
        blob = json.dumps(mission)
        for token in ("receipt", "link"):
            self.assertNotIn(token, blob.lower())

    def test_receipt_protections_intact(self):
        from backend.receipt import verify_receipt

        for rid in ("1902c485a31f4e45", "10d84a313fd44022"):
            self.assertEqual(verify_receipt(rid)["checks"]["integrity"], "pass")


if __name__ == "__main__":
    unittest.main()
