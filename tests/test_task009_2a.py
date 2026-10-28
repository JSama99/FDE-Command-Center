"""Task 009.2a: relevant proposals, rationale, readable report. Offline only."""

import hashlib
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from backend.server import handle_request, new_context
from tests.test_task009 import PREDICT, decide


def call(ctx, method, target, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    status, data, _ = handle_request(method, target, body, ctx)
    return status, data


PREDICT_NOACK = dict(PREDICT, hypothesis_id="H-QUEUE", expected_finding="no-ack",
                     expected_observation="The source log holds no case-003 acknowledgment.")


def ready_feed_probe(ctx, payload=PREDICT):
    call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
    call(ctx, "POST", "/api/experiment/predict", payload)
    call(ctx, "POST", "/api/experiment/reveal", {})
    call(ctx, "POST", "/api/experiment/assess", {})
    return ctx


def ready_audit(ctx):
    call(ctx, "POST", "/api/mission/diagnostic", {"choice": "timestamp-audit"})
    call(ctx, "GET", "/api/mission/diagnostic/result")
    return ctx


class ProposalRelevanceTest(unittest.TestCase):
    def test_ack_found_proposes_feed_reconciliation(self):
        ctx = ready_feed_probe(new_context())
        status, proposal = call(ctx, "GET", "/api/mission/proposal")
        self.assertEqual(status, 200)
        self.assertEqual((proposal["proposal_id"], proposal["version"]), ("PROP-002", "v1"))
        self.assertIn("reconciliation", proposal["text"])
        self.assertIn("case-003", proposal["text"])

    def test_contradicted_proposes_verification_not_remediation(self):
        ctx = ready_feed_probe(new_context(), PREDICT_NOACK)
        status, proposal = call(ctx, "GET", "/api/mission/proposal")
        self.assertEqual(status, 200)
        self.assertEqual((proposal["proposal_id"], proposal["version"]), ("PROP-004", "v1"))
        self.assertIn("verification", proposal["text"].lower())
        self.assertIn("No remediation", proposal["text"])

    def test_audit_proposes_coverage_reconciliation(self):
        ctx = ready_audit(new_context())
        status, proposal = call(ctx, "GET", "/api/mission/proposal")
        self.assertEqual(status, 200)
        self.assertEqual((proposal["proposal_id"], proposal["version"]), ("PROP-003", "v1"))
        self.assertIn("assignment", proposal["text"].lower())

    def test_historical_proposal_preserved_not_issued(self):
        from backend import mission as mission_module

        self.assertEqual((mission_module.HISTORICAL_PROPOSAL_ID,
                          mission_module.HISTORICAL_PROPOSAL_VERSION), ("PROP-001", "v1"))
        issued = set()
        for make_ready in (lambda c: ready_feed_probe(c),
                           lambda c: ready_feed_probe(c, PREDICT_NOACK),
                           ready_audit):
            _, proposal = call(make_ready(new_context()), "GET", "/api/mission/proposal")
            issued.add(proposal["proposal_id"])
        self.assertEqual(issued, {"PROP-002", "PROP-003", "PROP-004"})

    def test_stale_proposal_binding_rejected(self):
        ctx = ready_feed_probe(new_context())
        self.assertEqual(call(ctx, "POST", "/api/mission/intervention", {
            "decision": "approve", "note": "stale rationale",
            "proposal_id": "PROP-001", "proposal_version": "v1"})[0], 409)


class RationaleTest(unittest.TestCase):
    def bound_decide(self, ctx, note):
        _, proposal = call(ctx, "GET", "/api/mission/proposal")
        return call(ctx, "POST", "/api/mission/intervention", {
            "decision": "approve", "note": note,
            "proposal_id": proposal["proposal_id"],
            "proposal_version": proposal["version"]})

    def test_empty_rationale_rejected(self):
        ctx = ready_audit(new_context())
        self.assertEqual(self.bound_decide(ctx, "")[0], 400)

    def test_whitespace_rationale_rejected(self):
        ctx = ready_audit(new_context())
        self.assertEqual(self.bound_decide(ctx, "   \n  ")[0], 400)

    def test_stated_rationale_recorded(self):
        ctx = ready_audit(new_context())
        status, _ = self.bound_decide(ctx, "Coverage gap is minor; monitor one cycle.")
        self.assertEqual(status, 200)
        self.assertEqual(ctx["mission"]["intervention"]["note"],
                         "Coverage gap is minor; monitor one cycle.")


class GenuineRiskTest(unittest.TestCase):
    def test_risks_are_not_supporting_evidence(self):
        for make_ready in (lambda c: ready_feed_probe(c),
                           lambda c: ready_feed_probe(c, PREDICT_NOACK),
                           ready_audit):
            _, proposal = call(make_ready(new_context()), "GET", "/api/mission/proposal")
            self.assertTrue(proposal["risks"], msg=proposal["proposal_id"])
            refs = " ".join(proposal["supporting_evidence"]["refs"])
            for risk in proposal["risks"]:
                self.assertNotIn(risk, refs)
            self.assertTrue(proposal["stop_conditions"])
            self.assertTrue(proposal["next_role"])

    def test_no_invented_personnel(self):
        for make_ready in (lambda c: ready_feed_probe(c), ready_audit):
            _, proposal = call(make_ready(new_context()), "GET", "/api/mission/proposal")
            self.assertIsNone(re.search(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b",
                                        proposal["next_role"]),
                              msg=proposal["next_role"])


class ReadableReportTest(unittest.TestCase):
    def check_readable(self, report, proposal_id):
        readable = report["readable_sections"]
        self.assertEqual(len(readable), 13)
        flat = "\n".join(line for section in readable for line in section["lines"])
        self.assertNotIn('": ', flat)
        self.assertNotIn("{\"", flat)
        self.assertIn("Assigned within 1 hour: 5", flat)
        self.assertIn("within 1 hour of creation", flat)
        self.assertIn(f"Proposal {proposal_id}", flat)
        self.assertIn("Executed: False", flat)
        proposal = next(s for s in readable if s["title"] == "Intervention proposal")
        self.assertTrue(any(line.startswith("Risk:") for line in proposal["lines"]))
        self.assertTrue(any("Next responsible role:" in line for line in proposal["lines"]))

    def test_feed_probe_readable(self):
        ctx = ready_feed_probe(new_context())
        decide(ctx, "approve", "Reconciliation is bounded and read-only.")
        _, report = call(ctx, "GET", "/api/mission/report")
        self.check_readable(report, "PROP-002")

    def test_contradicted_readable(self):
        ctx = ready_feed_probe(new_context(), PREDICT_NOACK)
        decide(ctx, "defer", "Expectation contradicted; verify first.")
        _, report = call(ctx, "GET", "/api/mission/report")
        self.check_readable(report, "PROP-004")

    def test_audit_readable(self):
        ctx = ready_audit(new_context())
        decide(ctx, "reject", "Coverage work cannot close the ack gap.")
        _, report = call(ctx, "GET", "/api/mission/report")
        self.check_readable(report, "PROP-003")


class PreservationAndOfflineTest(unittest.TestCase):
    def test_fixtures_and_eval_history_untouched(self):
        root = Path(__file__).resolve().parents[1]
        before = hashlib.sha256(
            (root / "fixtures" / "case-001" / "events.csv").read_bytes()).hexdigest()
        ctx = ready_feed_probe(new_context())
        decide(ctx, "approve", "Bounded and read-only.")
        call(ctx, "GET", "/api/mission/report")
        after = hashlib.sha256(
            (root / "fixtures" / "case-001" / "events.csv").read_bytes()).hexdigest()
        self.assertEqual(before, after)
        frozen = (root / "eval-v2" / "manifest.json").read_bytes()
        for run in ("live-20261027T195244Z", "live-20261027T202322Z"):
            stored = (root / "evaluator-private" / "results" / run
                      / "manifest.json").read_bytes()
            self.assertEqual(stored, frozen, msg=run)

    def test_full_mission_without_network(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network used")):
            ctx = ready_feed_probe(new_context())
            self.assertEqual(decide(ctx, "approve", "Offline walkthrough.")[0], 200)
            self.assertEqual(call(ctx, "GET", "/api/mission/report")[0], 200)


if __name__ == "__main__":
    unittest.main()
