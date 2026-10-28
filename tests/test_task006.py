"""Task 006 tests: locked-prediction experiment. Stdlib unittest only."""

import json
import unittest
from pathlib import Path

from backend.experiment import (
    OUTCOME_MARKERS,
    ExperimentError,
    assess,
    build_registry,
    lock_prediction,
    new_experiment_state,
    public_view,
    reveal_outcome,
)
from backend.investigation import build_instructions, build_model_context
from backend.report import build_case_report
from backend.server import handle_request, new_context

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def prediction(finding="ack-found", hypo="H-ACK"):
    return {
        "hypothesis_id": hypo,
        "expected_finding": finding,
        "expected_observation": "Source log holds a case-003 ack missing from the feed.",
        "criteria": "ack-found supports H-ACK; no-ack supports H-QUEUE.",
        "refs": ["case-003", "events.csv"],
    }


def call(method, target, body=None, ctx=None):
    ctx = ctx if ctx is not None else new_context(ROOT)
    raw = None if body is None else json.dumps(body).encode("utf-8")
    status, payload, _ = handle_request(method, target, raw, ctx)
    return status, payload, ctx


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.registry = build_registry(ROOT)

    def test_full_lifecycle_supported(self):
        state = new_experiment_state()
        record = lock_prediction(state, prediction("ack-found"), self.registry, 1700000000)
        self.assertEqual(record["version"], "v1")
        self.assertIn("hash", record)
        self.assertEqual(state["status"], "prediction locked")
        outcome = reveal_outcome(state, 1700000001)
        self.assertEqual(outcome["finding"], "ack-found")
        assessment = assess(state)
        self.assertEqual(assessment["result"], "supported")
        self.assertTrue(assessment["refs"])

    def test_mismatch_contradicted(self):
        state = new_experiment_state()
        lock_prediction(state, prediction("no-ack", "H-QUEUE"), self.registry, 1700000000)
        reveal_outcome(state, 1700000001)
        self.assertEqual(assess(state)["result"], "contradicted")

    def test_assessment_deterministic(self):
        first, second = new_experiment_state(), new_experiment_state()
        for state in (first, second):
            lock_prediction(state, prediction("ack-found"), self.registry, 1700000000)
            reveal_outcome(state, 1700000001)
        self.assertEqual(assess(first), assess(second))


class NegativeTransitionTest(unittest.TestCase):
    def setUp(self):
        self.registry = build_registry(ROOT)

    def test_early_reveal_rejected(self):
        with self.assertRaises(ExperimentError):
            reveal_outcome(new_experiment_state(), 1)

    def test_early_assess_rejected(self):
        with self.assertRaises(ExperimentError):
            assess(new_experiment_state())

    def test_locked_prediction_immutable(self):
        state = new_experiment_state()
        first = lock_prediction(state, prediction("ack-found"), self.registry, 1)
        with self.assertRaises(ExperimentError):
            lock_prediction(state, prediction("ack-found"), self.registry, 2)
        with self.assertRaises(ExperimentError):
            lock_prediction(state, prediction("no-ack", "H-QUEUE"), self.registry, 3)
        self.assertEqual(state["prediction"], first)

    def test_invalid_prediction_rejected(self):
        state = new_experiment_state()
        bad = prediction()
        bad["hypothesis_id"] = "H-MADEUP"
        with self.assertRaises(ExperimentError):
            lock_prediction(state, bad, self.registry, 1)
        bad = prediction()
        bad["refs"] = ["case-999"]
        with self.assertRaises(ExperimentError):
            lock_prediction(state, bad, self.registry, 1)
        bad = prediction()
        bad["expected_finding"] = "maybe"
        with self.assertRaises(ExperimentError):
            lock_prediction(state, bad, self.registry, 1)
        self.assertEqual(state["status"], "proposed")

    def test_server_transition_codes(self):
        ctx = new_context(ROOT)
        status, _, _ = call("POST", "/api/experiment/reveal", {}, ctx)
        self.assertEqual(status, 409)
        status, _, _ = call("POST", "/api/experiment/assess", {}, ctx)
        self.assertEqual(status, 409)
        status, _, _ = call("POST", "/api/experiment/predict", prediction(), ctx)
        self.assertEqual(status, 200)
        status, _, _ = call("POST", "/api/experiment/predict", prediction(), ctx)
        self.assertEqual(status, 409)
        status, payload, _ = call("POST", "/api/experiment/reveal", {}, ctx)
        self.assertEqual(status, 200)
        self.assertIn(OUTCOME_MARKERS[0], json.dumps(payload))
        status, payload, _ = call("POST", "/api/experiment/assess", {}, ctx)
        self.assertEqual(status, 200)
        self.assertEqual(payload["assessment"]["result"], "supported")


class DisclosureTest(unittest.TestCase):
    def test_withheld_everywhere_before_reveal(self):
        ctx = new_context(ROOT)
        bodies = []
        for method, target in (
            ("GET", "/api/experiment"),
            ("GET", "/api/report"),
            ("GET", "/api/investigation?mode=mock"),
        ):
            status, payload, _ = call(method, target, None, ctx)
            self.assertEqual(status, 200)
            bodies.append(json.dumps(payload))
        report = build_case_report(ROOT)
        bodies.append(json.dumps(report))
        bodies.append(json.dumps(build_model_context(report)))
        from backend.investigation import build_evidence_registry

        bodies.append(build_instructions(build_evidence_registry(report)))
        for name in ("investigate.html", "investigate.js", "case-001.html", "case-001.json", "index.html", "app.js"):
            bodies.append((FRONTEND / name).read_text(encoding="utf-8"))
        for body in bodies:
            for marker in OUTCOME_MARKERS:
                self.assertNotIn(marker, body)

    def test_fresh_session_sees_no_outcome(self):
        status, payload, _ = call("GET", "/api/experiment")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "proposed")
        self.assertNotIn("outcome", payload)
        self.assertNotIn("assessment", payload)


class ExperimentPanelTest(unittest.TestCase):
    def test_panel_wires_lifecycle(self):
        html = (FRONTEND / "investigate.html").read_text(encoding="utf-8")
        js = (FRONTEND / "investigate.js").read_text(encoding="utf-8")
        for token in ("/api/experiment", "/api/experiment/predict", "/api/experiment/reveal", "/api/experiment/assess"):
            self.assertIn(token, js)
        for token in ("expLockBtn", "expRevealBtn", "expAssessBtn"):
            self.assertIn(token, html)
        for token in ("withheld", "locked", "revealed", "assessed"):
            self.assertIn(token, js)
        for marker in OUTCOME_MARKERS:
            self.assertNotIn(marker, html)
            self.assertNotIn(marker, js)


if __name__ == "__main__":
    unittest.main()
