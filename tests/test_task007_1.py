"""Task 007.1 tests: prediction fidelity and evidence-based revision."""

import copy
import json
import unittest
from pathlib import Path

from backend.ai_prediction import mock_revision_payload, validate_revision
from backend.investigation import build_evidence_registry
from backend.report import build_case_report
from backend.server import handle_request, new_context

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

REVIEWED_FIELDS = (
    "hypothesis_id",
    "expected_finding",
    "expected_observation",
    "test_procedure",
    "criteria",
    "uncertainty",
    "alternatives",
    "refs",
    "metrics",
)


def call(method, target, body=None, ctx=None):
    ctx = ctx if ctx is not None else new_context(ROOT)
    raw = None if body is None else json.dumps(body).encode("utf-8")
    status, payload, _ = handle_request(method, target, raw, ctx)
    return status, payload, ctx


def assessed_ctx():
    ctx = new_context(ROOT)
    status, _, _ = call("POST", "/api/prediction/generate", {"mode": "mock"}, ctx)
    assert status == 200
    status, _, _ = call("POST", "/api/prediction/lock", {"confirmed": True}, ctx)
    assert status == 200
    status, _, _ = call("POST", "/api/experiment/reveal", {}, ctx)
    assert status == 200
    status, _, _ = call("POST", "/api/experiment/assess", {}, ctx)
    assert status == 200
    return ctx


class FidelityTest(unittest.TestCase):
    def test_locked_record_matches_reviewed_prediction(self):
        ctx = new_context(ROOT)
        status, envelope, _ = call("POST", "/api/prediction/generate", {"mode": "mock"}, ctx)
        self.assertEqual(status, 200)
        reviewed = envelope["prediction"]
        status, locked, _ = call("POST", "/api/prediction/lock", {"confirmed": True}, ctx)
        self.assertEqual(status, 200)
        record = locked["prediction"]
        for field in REVIEWED_FIELDS:
            self.assertIn(field, record)
            self.assertEqual(record[field], reviewed[field])

    def test_no_invisible_normalization(self):
        ctx = new_context(ROOT)
        _, envelope, _ = call("POST", "/api/prediction/generate", {"mode": "mock"}, ctx)
        _, locked, _ = call("POST", "/api/prediction/lock", {"confirmed": True}, ctx)
        reviewed = envelope["prediction"]
        record = locked["prediction"]
        self.assertEqual(record["expected_observation"], reviewed["expected_observation"])
        self.assertEqual(record["criteria"], reviewed["criteria"])
        self.assertEqual(record["alternatives"], reviewed["alternatives"])


class StrengthenedRevisionTest(unittest.TestCase):
    def setUp(self):
        self.ctx = assessed_ctx()
        self.exp = self.ctx["experiment"]
        self.registry = build_evidence_registry(build_case_report(ROOT))

    def validate(self, payload):
        return validate_revision(
            payload, self.registry,
            self.exp["prediction"], self.exp["outcome"], self.exp["assessment"],
        )

    def test_mock_revision_meets_new_schema(self):
        self.assertTrue(self.validate(mock_revision_payload()))

    def test_incomplete_revision_rejected(self):
        for drop in ("effect_on_h_queue", "remaining_alternatives", "unresolved_questions",
                     "reversal_evidence", "new_evidence", "deterministic_assessment"):
            bad = mock_revision_payload()
            del bad[drop]
            with self.assertRaises(Exception, msg=drop):
                self.validate(bad)
        bad = mock_revision_payload()
        del bad["next_test"]["expected_observations"]
        with self.assertRaises(Exception):
            self.validate(bad)

    def test_unsupported_causal_claims_rejected(self):
        bad = mock_revision_payload()
        bad["effect_on_h_ack"]["stance"] = "proven"
        with self.assertRaises(Exception):
            self.validate(bad)
        bad = mock_revision_payload()
        bad["effect_on_h_ack"]["reason"] = "This verified root cause explains everything."
        with self.assertRaises(Exception):
            self.validate(bad)
        bad = mock_revision_payload()
        bad["effect_on_h_ack"]["stance"] = "contradicted"
        with self.assertRaises(Exception):
            self.validate(bad)

    def test_original_records_preserved(self):
        before = {
            key: copy.deepcopy(self.exp[key])
            for key in ("prediction", "outcome", "assessment")
        }
        status, _, _ = call("POST", "/api/revision/generate", {"mode": "mock"}, self.ctx)
        self.assertEqual(status, 200)
        for key, snapshot in before.items():
            self.assertEqual(self.exp[key], snapshot)

    def test_match_is_support_not_proof(self):
        status, result, _ = call("POST", "/api/revision/generate", {"mode": "mock"}, self.ctx)
        self.assertEqual(status, 200)
        blob = json.dumps(result).lower()
        for phrase in ("verified root cause", "proven root cause", "root cause proven",
                       "root cause confirmed", "causal explanation validated", "causality proven"):
            self.assertNotIn(phrase, blob)
        self.assertEqual(result["revision"]["effect_on_h_ack"]["stance"], "supported")
        self.assertIn("reason", result["revision"]["effect_on_h_ack"])


class SeparationPanelTest(unittest.TestCase):
    def test_terms_and_separation(self):
        html = (FRONTEND / "investigate.html").read_text(encoding="utf-8")
        js = (FRONTEND / "investigate.js").read_text(encoding="utf-8")
        self.assertNotIn("human-validated conclusion", html + js)
        self.assertIn("human-reviewed revision", html)
        self.assertIn("support is not proof", html.lower())
        self.assertIn("agreement is support, not proof", js)


if __name__ == "__main__":
    unittest.main()
