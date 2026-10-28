"""Task 007.2 tests: evidence scope, audit display, no overgeneralization."""

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


def call(method, target, body=None, ctx=None):
    ctx = ctx if ctx is not None else new_context(ROOT)
    raw = None if body is None else json.dumps(body).encode("utf-8")
    status, payload, _ = handle_request(method, target, raw, ctx)
    return status, payload, ctx


def assessed_ctx():
    ctx = new_context(ROOT)
    for method, target, body in (
        ("POST", "/api/prediction/generate", {"mode": "mock"}),
        ("POST", "/api/prediction/lock", {"confirmed": True}),
        ("POST", "/api/experiment/reveal", {}),
        ("POST", "/api/experiment/assess", {}),
    ):
        status, _, _ = call(method, target, body, ctx)
        assert status == 200, (method, target, status)
    return ctx


class ScopeRuleTest(unittest.TestCase):
    def setUp(self):
        self.ctx = assessed_ctx()
        self.exp = self.ctx["experiment"]
        self.registry = build_evidence_registry(build_case_report(ROOT))

    def validate(self, payload):
        return validate_revision(
            payload, self.registry,
            self.exp["prediction"], self.exp["outcome"], self.exp["assessment"],
        )

    def test_corrected_exp001_shape(self):
        revision = self.validate(mock_revision_payload())
        self.assertEqual(
            (revision["effect_on_h_ack"]["stance"], revision["effect_on_h_ack"]["scope"]),
            ("supported", "single-case"),
        )
        self.assertEqual(
            (revision["effect_on_h_queue"]["stance"], revision["effect_on_h_queue"]["scope"]),
            ("unresolved", "population"),
        )
        blob = json.dumps(revision).lower()
        self.assertNotIn("root cause", blob.replace("no organization-wide root cause", ""))

    def test_single_case_cannot_disprove_wide_hypothesis(self):
        bad = mock_revision_payload()
        bad["effect_on_h_queue"] = {
            "stance": "contradicted",
            "scope": "single-case",
            "reason": "case-003 was assigned on time.",
            "refs": ["case-003", "events.csv"],
        }
        with self.assertRaises(Exception) as ctx:
            self.validate(bad)
        self.assertEqual(ctx.exception.category, "overgeneralization")

    def test_population_scope_needs_breadth(self):
        bad = mock_revision_payload()
        bad["effect_on_h_queue"] = {
            "stance": "unresolved",
            "scope": "population",
            "reason": "Only one case checked.",
            "refs": ["case-003"],
        }
        with self.assertRaises(Exception) as ctx:
            self.validate(bad)
        self.assertEqual(ctx.exception.category, "scope-mismatch")

    def test_missing_scope_rejected(self):
        bad = mock_revision_payload()
        del bad["effect_on_h_ack"]["scope"]
        with self.assertRaises(Exception) as ctx:
            self.validate(bad)
        self.assertEqual(ctx.exception.category, "missing-scope")

    def test_supported_population_effect_passes_with_breadth(self):
        good = mock_revision_payload()
        good["effect_on_h_queue"] = {
            "stance": "supported",
            "scope": "population",
            "reason": "Demonstration: several unassigned cases point at queue handling.",
            "refs": ["case-004", "case-006", "events.csv"],
        }
        self.assertTrue(self.validate(good))


class AuditEqualityTest(unittest.TestCase):
    def test_reviewed_and_locked_match_wholesale(self):
        ctx = new_context(ROOT)
        _, envelope, _ = call("POST", "/api/prediction/generate", {"mode": "mock"}, ctx)
        reviewed = envelope["prediction"]
        _, locked, _ = call("POST", "/api/prediction/lock", {"confirmed": True}, ctx)
        record = locked["prediction"]
        self.assertTrue(set(reviewed) <= set(record), "locked record must keep every reviewed field")
        for key in reviewed:
            self.assertEqual(record[key], reviewed[key])
        for key in ("model_id", "prediction_version", "locked_at", "hash"):
            self.assertIn(key, record)


class AuditPanelTest(unittest.TestCase):
    def test_locked_panel_shows_every_field(self):
        js = (FRONTEND / "investigate.js").read_text(encoding="utf-8")
        for token in ("test_procedure", "criteria", "uncertainty", "alternatives",
                      "metrics", "model_id", "generated_at", "locked_at", "hash"):
            self.assertIn(token, js)

    def test_five_way_distinction_visible(self):
        html = (FRONTEND / "investigate.html").read_text(encoding="utf-8")
        js = (FRONTEND / "investigate.js").read_text(encoding="utf-8")
        self.assertIn("prediction agreement", js)
        self.assertIn("finding</span>", js)
        self.assertIn("No organization-wide root cause established", js)
        self.assertIn("Causal validation: none performed", js)
        for label in ("human-authored prediction", "ai-generated prediction",
                      "deterministic assessment", "ai-generated interpretation",
                      "human-reviewed revision"):
            self.assertIn(label, html)


if __name__ == "__main__":
    unittest.main()
