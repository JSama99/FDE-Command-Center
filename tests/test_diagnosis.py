"""Task 005.1 regression tests: live-rejection diagnosis. Stdlib unittest only.

Reproduces the live failure mode: model output shaped by the old,
under-specified prompt (no basis fields, guessed reference IDs) is rejected
by the validator. The strengthened instructions and the validator now share
one documented contract, and rejections carry safe diagnostics.
"""

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from backend.investigation import (
    DOC_REFS,
    EXPECTED_SECTIONS,
    OBSERVATION_BASES,
    DiagnosticError,
    InvestigationValidationError,
    build_evidence_registry,
    build_instructions,
    diagnostic_report,
    produce_investigation,
    validate_investigation,
)
from backend.meta_adapter import MockAdapter
from backend.report import build_case_report
from backend.server import handle_request, new_context

ROOT = Path(__file__).resolve().parents[1]


def old_style_model_output() -> dict:
    """Realistic output under the old prompt: sections present, but no basis
    fields and guessed reference IDs the registry never issued."""
    return {
        "observations": [
            {"text": "Policy requires assignment within 1 hour.", "refs": ["policy.md"]},
            {"text": "Dispatcher says the queue sometimes backs up.", "refs": ["dispatcher interview"]},
        ],
        "competing_hypotheses": [
            {"text": "Backlog explains the delays.", "refs": ["events.csv"]},
        ],
        "unresolved_questions": ["What about the late-day cases?"],
        "diagnostic_experiments": [
            {"text": "Extend observation windows.", "refs": ["events.csv"]},
        ],
        "provisional_recommendation": {
            "text": "Review overnight coverage.",
            "refs": ["events.csv"],
        },
        "counter_evidence": [
            {"text": "One case met both deadlines.", "refs": ["case-001"]},
        ],
    }


def new_contract_model_output() -> dict:
    """Realistic output following the strengthened instructions."""
    return {
        "observations": [
            {"text": "Policy requires assignment within 1 hour.", "refs": ["policy"], "basis": "verified-quote"},
            {"text": "Dispatcher reports overnight backlog.", "refs": ["dispatcher"], "basis": "stakeholder-report"},
            {"text": "3 of 7 eligible urgent cases are confirmed misses.", "refs": ["events.csv"], "basis": "computed"},
        ],
        "competing_hypotheses": [
            {"text": "Backlog explains unassigned cases.", "refs": ["dispatcher", "events.csv"], "status": "hypothesis"},
        ],
        "unresolved_questions": ["Do incomplete windows hide further misses?"],
        "diagnostic_experiments": [
            {"text": "Extend late-day windows, then recompute.", "refs": ["events.csv"]},
        ],
        "provisional_recommendation": {
            "text": "Review overnight coverage. No change without approval.",
            "refs": ["events.csv", "dispatcher"],
            "requires_human_approval": True,
            "executes_production_change": False,
        },
        "counter_evidence": [
            {"text": "case-001 met both deadlines.", "refs": ["case-001"]},
        ],
        "metrics": {"Confirmed deadline misses": 3},
    }


class LiveRejectionDiagnosisTest(unittest.TestCase):
    def setUp(self):
        self.registry = build_evidence_registry(build_case_report(ROOT))

    def test_old_style_output_rejected_at_basis(self):
        with self.assertRaises(DiagnosticError) as ctx:
            validate_investigation(old_style_model_output(), self.registry)
        self.assertEqual(ctx.exception.category, "unknown-reference")
        # The guessed "policy.md" ID fails before basis is even reached.
        self.assertEqual(ctx.exception.ref, "policy.md")
        self.assertIn("observations[0].refs", ctx.exception.field_path)

    def test_missing_basis_is_reported_exactly(self):
        bad = new_contract_model_output()
        del bad["observations"][0]["basis"]
        with self.assertRaises(DiagnosticError) as ctx:
            validate_investigation(bad, self.registry)
        self.assertEqual(
            (ctx.exception.category, ctx.exception.field_path),
            ("missing-field", "observations[0].basis"),
        )

    def test_diagnostics_carry_stage_and_ref(self):
        try:
            validate_investigation(old_style_model_output(), self.registry)
            self.fail("expected rejection")
        except DiagnosticError as exc:
            record = diagnostic_report(exc, "corr123", "evidence-validation")
        self.assertEqual(
            record,
            {
                "stage": "evidence-validation",
                "category": "unknown-reference",
                "field_path": "observations[0].refs",
                "ref": "policy.md",
                "correlation_id": "corr123",
                "failed_at": "evidence-validation",
            },
        )

    def test_new_contract_output_passes(self):
        self.assertTrue(validate_investigation(new_contract_model_output(), self.registry))

    def test_instructions_and_validator_share_one_contract(self):
        text = build_instructions(self.registry)
        for section in EXPECTED_SECTIONS:
            self.assertIn(section, text)
        for ref in DOC_REFS:
            self.assertIn(f'"{ref}"', text)
        for label in self.registry["metrics"]:
            self.assertIn(f'"{label}"', text)
        for basis in OBSERVATION_BASES:
            self.assertIn(f'"{basis}"', text)
        for token in ("requires_human_approval", "executes_production_change", '"hypothesis"'):
            self.assertIn(token, text)
        for case in ("case-002", "case-008"):
            self.assertIn(f'"{case}"', text)

    def test_produce_passes_instructions_to_adapter(self):
        adapter = MockAdapter(new_contract_model_output())
        produce_investigation(adapter, ROOT)
        self.assertIsNotNone(adapter.last_instructions)
        self.assertIn("observations", adapter.last_instructions)
        self.assertIn('"policy"', adapter.last_instructions)


class ServerDiagnosticsTest(unittest.TestCase):
    def _live_failure(self):
        inner = json.dumps(old_style_model_output())
        envelope = {
            "id": "resp_fictional_003",
            "object": "response",
            "status": "completed",
            "model": "muse-spark-1.3",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": inner}],
                }
            ],
        }

        class FakeResponse:
            def read(self):
                return json.dumps(envelope).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        ctx = new_context(ROOT)
        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "fictional-test-key"}, clear=False):
            with mock.patch("urllib.request.urlopen", return_value=FakeResponse()):
                status, payload, _ = handle_request(
                    "POST", "/api/investigation",
                    json.dumps({"mode": "live"}).encode("utf-8"), ctx,
                )
        return status, payload, ctx

    def test_live_rejection_reports_diagnostics_safely(self):
        status, payload, _ = self._live_failure()
        self.assertEqual(status, 502)
        self.assertEqual(payload["error"], "invalid_investigation")
        diag = payload["diagnostics"]
        self.assertEqual(diag["category"], "unknown-reference")
        self.assertEqual(diag["field_path"], "observations[0].refs")
        self.assertEqual(diag["ref"], "policy.md")
        self.assertEqual(diag["failed_at"], "evidence-validation")
        self.assertTrue(diag["correlation_id"])
        body = json.dumps(payload)
        self.assertNotIn("fictional-test-key", body)
        self.assertNotIn("Policy requires assignment within 1 hour.", body)

    def test_correlation_ids_are_unique(self):
        _, first, _ = self._live_failure()
        _, second, _ = self._live_failure()
        self.assertNotEqual(
            first["diagnostics"]["correlation_id"], second["diagnostics"]["correlation_id"]
        )

    def test_diagnostics_endpoint_serves_last_record(self):
        _, payload, ctx = self._live_failure()
        status, latest, _ = handle_request("GET", "/api/diagnostics/latest", None, ctx)
        self.assertEqual(status, 200)
        self.assertEqual(latest, payload["diagnostics"])

    def test_diagnostics_endpoint_empty(self):
        status, _, _ = handle_request("GET", "/api/diagnostics/latest", None, new_context(ROOT))
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
