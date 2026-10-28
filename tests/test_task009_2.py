"""Task 009.2: proposal binding, expanded report, preservation. Offline only."""

import json
import unittest
from pathlib import Path

from backend.server import handle_request, new_context
from tests.test_task009 import PREDICT, decide


def call(ctx, method, target, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    status, data, _ = handle_request(method, target, body, ctx)
    return status, data


def ready_feed_probe(ctx):
    call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
    call(ctx, "POST", "/api/experiment/predict", PREDICT)
    call(ctx, "POST", "/api/experiment/reveal", {})
    call(ctx, "POST", "/api/experiment/assess", {})
    return ctx


def ready_audit(ctx):
    call(ctx, "POST", "/api/mission/diagnostic", {"choice": "timestamp-audit"})
    call(ctx, "GET", "/api/mission/diagnostic/result")
    return ctx


class ProposalBindingTest(unittest.TestCase):
    def test_proposal_shown_before_approval(self):
        ctx = ready_feed_probe(new_context())
        status, proposal = call(ctx, "GET", "/api/mission/proposal")
        self.assertEqual(status, 200)
        for key in ("proposal_id", "version", "text", "supporting_evidence",
                    "risks", "scope", "reversible", "approval_note"):
            self.assertIn(key, proposal)
        self.assertTrue(proposal["supporting_evidence"]["refs"])
        self.assertTrue(proposal["risks"])
        self.assertTrue(proposal["reversible"])

    def test_proposal_too_early(self):
        ctx = new_context()
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        self.assertEqual(call(ctx, "GET", "/api/mission/proposal")[0], 409)

    def test_decision_requires_matching_proposal(self):
        ctx = ready_audit(new_context())
        self.assertEqual(call(ctx, "POST", "/api/mission/intervention",
                              {"decision": "approve"})[0], 409)
        self.assertEqual(call(ctx, "POST", "/api/mission/intervention", {
            "decision": "approve", "proposal_id": "PROP-999",
            "proposal_version": "v1"})[0], 409)
        self.assertEqual(decide(ctx, "approve")[0], 200)

    def test_decision_records_proposal_identity(self):
        ctx = ready_feed_probe(new_context())
        _, proposal = call(ctx, "GET", "/api/mission/proposal")
        self.assertEqual(proposal["proposal_id"], "PROP-002")
        _, data = decide(ctx, "defer", "needs ops review")
        record = ctx["mission"]["intervention"]
        self.assertEqual(record["proposal"]["proposal_id"], proposal["proposal_id"])
        self.assertEqual(record["proposal"]["version"], proposal["version"])
        self.assertEqual(record["proposal"]["text"], proposal["text"])
        self.assertEqual(record["decision"], "defer")
        self.assertEqual(record["note"], "needs ops review")
        self.assertFalse(record["executed"])

    def test_repeated_decision_rejected_even_with_binding(self):
        ctx = ready_audit(new_context())
        _, proposal = call(ctx, "GET", "/api/mission/proposal")
        decide(ctx, "approve")
        self.assertEqual(call(ctx, "POST", "/api/mission/intervention", {
            "decision": "reject", "proposal_id": proposal["proposal_id"],
            "proposal_version": proposal["version"]})[0], 409)


class ReportCompletenessTest(unittest.TestCase):
    REQUIRED_TITLES = (
        "Mission objective", "Operating constraints",
        "Key evidence and deterministic metrics", "Competing hypotheses",
        "Chosen diagnostic test", "Locked prediction and timestamp",
        "Revealed observation and source", "Deterministic assessment",
        "Revised interpretation and remaining uncertainties",
        "Intervention proposal", "Human decision and rationale",
        "Risk, rollback, and follow-up", "Production-action confirmation",
    )
    ALLOWED_LAYERS = {"mission context", "confirmed observation",
                      "model interpretation", "deterministic calculation",
                      "human decision"}

    def check_report(self, report, proposal_id="PROP-002"):
        titles = [s["title"] for s in report["sections"]]
        for required in self.REQUIRED_TITLES:
            self.assertIn(required, titles, msg=required)
        layers = {s["layer"] for s in report["sections"]}
        self.assertTrue(layers.issubset(self.ALLOWED_LAYERS), msg=layers)
        for needed in ("confirmed observation", "model interpretation",
                       "deterministic calculation", "human decision"):
            self.assertIn(needed, layers, msg=needed)
        decision = next(s for s in report["sections"]
                        if s["title"] == "Human decision and rationale")
        self.assertEqual(decision["body"]["proposal_id"], proposal_id)
        confirm = next(s for s in report["sections"]
                       if s["title"] == "Production-action confirmation")
        self.assertFalse(confirm["body"]["executed"])

    def test_feed_probe_report_complete(self):
        ctx = ready_feed_probe(new_context())
        decide(ctx, "approve", "reversible advisory step")
        _, report = call(ctx, "GET", "/api/mission/report")
        self.check_report(report)
        prediction = next(s for s in report["sections"]
                          if s["title"] == "Locked prediction and timestamp")
        self.assertEqual(prediction["body"]["hash"],
                         ctx["experiment"]["prediction"]["hash"])
        self.assertIn("locked_at", prediction["body"])

    def test_audit_report_complete(self):
        ctx = ready_audit(new_context())
        decide(ctx, "reject", "gap needs feed-side work")
        _, report = call(ctx, "GET", "/api/mission/report")
        self.check_report(report, proposal_id="PROP-003")


class HistoricalPreservationTest(unittest.TestCase):
    def test_frozen_eval_manifests_unchanged(self):
        root = Path(__file__).resolve().parents[1]
        frozen_v2 = (root / "eval-v2" / "manifest.json").read_bytes()
        for run in ("live-20261027T195244Z", "live-20261027T202322Z"):
            stored = (root / "evaluator-private" / "results" / run
                      / "manifest.json").read_bytes()
            self.assertEqual(stored, frozen_v2, msg=run)
        frozen_v3 = (root / "eval-v3" / "manifest.json").read_bytes()
        stored = (root / "evaluator-private" / "results"
                  / "live-20261027T204820Z" / "manifest.json").read_bytes()
        self.assertEqual(stored, frozen_v3)

    def test_mission_leaves_experiment_engine_untouched(self):
        import backend.experiment as experiment

        before = list(experiment.HYPOTHESES)
        ctx = ready_feed_probe(new_context())
        decide(ctx, "approve")
        call(ctx, "GET", "/api/mission/report")
        self.assertEqual(list(experiment.HYPOTHESES), before)
        self.assertEqual(ctx["experiment"]["status"], "assessed")


if __name__ == "__main__":
    unittest.main()
