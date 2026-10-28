"""Task 007 tests: AI prediction, revision, and learning loop. Stdlib unittest only."""

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from backend.ai_prediction import (
    build_prediction_context,
    build_prediction_instructions,
    mock_prediction_payload,
    validate_prediction,
)
from backend.experiment import OUTCOME_MARKERS
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


def envelope(inner_text):
    return {
        "id": "resp_fictional_007",
        "object": "response",
        "status": "completed",
        "model": "muse-spark-1.3",
        "output": [
            {"type": "message", "role": "assistant",
             "content": [{"type": "output_text", "text": inner_text}]},
        ],
    }


class FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def full_mock_cycle(ctx):
    status, _, _ = call("POST", "/api/prediction/generate", {"mode": "mock"}, ctx)
    assert status == 200, status
    status, locked, _ = call("POST", "/api/prediction/lock", {"confirmed": True}, ctx)
    assert status == 200, locked
    status, _, _ = call("POST", "/api/experiment/reveal", {}, ctx)
    assert status == 200
    status, _, _ = call("POST", "/api/experiment/assess", {}, ctx)
    assert status == 200
    return locked


class AIPredictionTest(unittest.TestCase):
    def test_successful_ai_prediction(self):
        status, payload, _ = call("POST", "/api/prediction/generate", {"mode": "mock"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["origin"], "ai-generated")
        self.assertEqual(payload["prediction_version"], "v2")
        self.assertIn("eligible_urgent", payload["evidence_cutoff"])
        self.assertTrue(payload["requires_confirmation"])
        self.assertTrue(payload["demonstration_only"])

    def test_invalid_refs_and_numbers_rejected(self):
        bad = mock_prediction_payload()
        bad["refs"] = ["case-999"]
        with self.assertRaises(Exception):
            validate_prediction(bad, build_evidence_registry(build_case_report(ROOT)))
        bad = mock_prediction_payload()
        bad["metrics"] = {"Eligible urgent cases": 99}
        with self.assertRaises(Exception):
            validate_prediction(bad, build_evidence_registry(build_case_report(ROOT)))

    def test_malformed_live_response(self):
        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "fictional-test-key"}, clear=False):
            with mock.patch("urllib.request.urlopen", return_value=FakeResponse(envelope("{bad json"))):
                status, payload, _ = call("POST", "/api/prediction/generate", {"mode": "live"})
        self.assertEqual(status, 502)
        self.assertEqual(payload["diagnostics"]["failed_at"], "response-parsing")

    def test_lock_requires_confirmation(self):
        ctx = new_context(ROOT)
        call("POST", "/api/prediction/generate", {"mode": "mock"}, ctx)
        status, payload, _ = call("POST", "/api/prediction/lock", {"confirmed": False}, ctx)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "confirmation-required")

    def test_ai_lock_immutable_and_blocks_human_path(self):
        ctx = new_context(ROOT)
        call("POST", "/api/prediction/generate", {"mode": "mock"}, ctx)
        status, locked, _ = call("POST", "/api/prediction/lock", {"confirmed": True}, ctx)
        self.assertEqual(status, 200)
        self.assertEqual(locked["prediction"]["origin"], "ai-generated")
        self.assertIn("hash", locked["prediction"])
        status, _, _ = call("POST", "/api/prediction/lock", {"confirmed": True}, ctx)
        self.assertEqual(status, 409)
        status, _, _ = call("POST", "/api/experiment/predict", {
            "hypothesis_id": "H-QUEUE", "expected_finding": "no-ack",
            "expected_observation": "x", "criteria": "y", "refs": ["case-003"],
        }, ctx)
        self.assertEqual(status, 409)

    def test_early_reveal_rejected(self):
        ctx = new_context(ROOT)
        call("POST", "/api/prediction/generate", {"mode": "mock"}, ctx)
        status, _, _ = call("POST", "/api/experiment/reveal", {}, ctx)
        self.assertEqual(status, 409)

    def test_missing_credentials_and_provider_failure(self):
        from backend.meta_adapter import CREDENTIAL_ENV_VAR, LEGACY_CREDENTIAL_ENV_VAR

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(CREDENTIAL_ENV_VAR, None)
            os.environ.pop(LEGACY_CREDENTIAL_ENV_VAR, None)
            status, payload, _ = call("POST", "/api/prediction/generate", {"mode": "live"})
        self.assertEqual(status, 503)
        import urllib.error

        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "fictional-test-key"}, clear=False):
            with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
                status, _, _ = call("POST", "/api/prediction/generate", {"mode": "live"})
        self.assertEqual(status, 502)

    def test_no_unintended_paid_calls(self):
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network used")):
            status, _, _ = call("POST", "/api/prediction/generate", {"mode": "mock"})
            self.assertEqual(status, 200)
            ctx = new_context(ROOT)
            full_mock_cycle(ctx)
            status, _, _ = call("POST", "/api/revision/generate", {"mode": "mock"}, ctx)
            self.assertEqual(status, 200)


class LeakageTest(unittest.TestCase):
    def test_pre_reveal_context_has_no_answer(self):
        report = build_case_report(ROOT)
        registry = build_evidence_registry(report)
        blob = json.dumps(build_prediction_context(report)) + build_prediction_instructions(registry)
        blob += json.dumps(mock_prediction_payload())
        for marker in OUTCOME_MARKERS:
            self.assertNotIn(marker, blob)

    def test_live_request_body_has_no_answer(self):
        captured = {}
        inner = json.dumps(mock_prediction_payload())

        def fake(request, timeout=None):
            captured["body"] = request.data.decode("utf-8")
            return FakeResponse(envelope(inner))

        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "fictional-test-key"}, clear=False):
            with mock.patch("urllib.request.urlopen", fake):
                status, _, _ = call("POST", "/api/prediction/generate", {"mode": "live"})
        self.assertEqual(status, 200)
        for marker in OUTCOME_MARKERS:
            self.assertNotIn(marker, captured["body"])


class RevisionTest(unittest.TestCase):
    def test_revision_lifecycle_and_preservation(self):
        ctx = new_context(ROOT)
        locked = full_mock_cycle(ctx)
        before = json.dumps(ctx["experiment"]["prediction"])
        status, result, _ = call("POST", "/api/revision/generate", {"mode": "mock"}, ctx)
        self.assertEqual(status, 200)
        self.assertEqual(result["revision"]["effect_on_h_ack"]["stance"], "supported")
        self.assertEqual(result["revision"]["effect_on_h_ack"]["scope"], "single-case")
        self.assertEqual(result["revision"]["effect_on_h_queue"]["stance"], "unresolved")
        self.assertEqual(result["revision"]["effect_on_h_queue"]["scope"], "population")
        self.assertEqual(json.dumps(ctx["experiment"]["prediction"]), before)
        self.assertIn("outcome", json.dumps(ctx["experiment"]))
        status, approved, _ = call("POST", "/api/revision/approve", {"decision": "approve"}, ctx)
        self.assertEqual(status, 200)
        self.assertFalse(approved["executed"])

    def test_revision_requires_assessment(self):
        ctx = new_context(ROOT)
        status, _, _ = call("POST", "/api/revision/generate", {"mode": "mock"}, ctx)
        self.assertEqual(status, 409)

    def test_match_is_not_a_verified_cause(self):
        ctx = new_context(ROOT)
        full_mock_cycle(ctx)
        status, result, _ = call("POST", "/api/revision/generate", {"mode": "mock"}, ctx)
        self.assertEqual(status, 200)
        blob = json.dumps(result).lower()
        for phrase in ("verified root cause", "proven root cause", "root cause proven"):
            self.assertNotIn(phrase, blob)

    def test_revision_rejects_bad_comparison(self):
        from backend.ai_prediction import mock_revision_payload, validate_revision

        report = build_case_report(ROOT)
        registry = build_evidence_registry(report)
        ctx = new_context(ROOT)
        full_mock_cycle(ctx)
        exp = ctx["experiment"]
        bad = mock_revision_payload()
        bad["deterministic_assessment"]["result"] = "contradicted"
        with self.assertRaises(Exception):
            validate_revision(bad, registry, exp["prediction"], exp["outcome"], exp["assessment"])


class RevisionPanelTest(unittest.TestCase):
    def test_panel_covers_full_loop(self):
        html = (FRONTEND / "investigate.html").read_text(encoding="utf-8")
        js = (FRONTEND / "investigate.js").read_text(encoding="utf-8")
        for token in ("/api/prediction/generate", "/api/prediction/lock", "/api/revision/generate", "/api/revision/approve"):
            self.assertIn(token, js)
        for token in ("aiGenMockBtn", "aiLockBtn", "revMockBtn", "revApproveBtn", "human-reviewed revision"):
            self.assertIn(token, html if "Btn" in token else html + js)
        for label in ("human-authored prediction", "ai-generated prediction", "deterministic assessment",
                      "ai-generated interpretation", "human-reviewed revision"):
            self.assertIn(label, html)
        self.assertNotIn("human-validated conclusion", html + js)
        for marker in OUTCOME_MARKERS:
            self.assertNotIn(marker, html)
            self.assertNotIn(marker, js)


if __name__ == "__main__":
    unittest.main()
