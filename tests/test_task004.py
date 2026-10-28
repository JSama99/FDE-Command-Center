"""Task 004 tests: Muse Spark adapter + validated investigation. Stdlib unittest only."""

import copy
import os
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from backend.investigation import (
    InvestigationValidationError,
    build_evidence_registry,
    build_model_context,
    classify_claim,
    produce_investigation,
    validate_investigation,
)
from backend.meta_adapter import (
    CREDENTIAL_ENV_VAR,
    ENDPOINT_ENV_VAR,
    MODEL_ID,
    MalformedResponseError,
    MetaConfig,
    MetaModelAdapter,
    MissingCredentialsError,
    MockAdapter,
    ProviderError,
)
from backend.quotes import load_case_documents, verify_quote
from backend.report import build_case_report

ROOT = Path(__file__).resolve().parents[1]


def valid_payload() -> dict:
    return {
        "observations": [
            {
                "text": "Policy requires urgent assignment within 1 hour of creation.",
                "refs": ["policy"],
                "basis": "verified-quote",
            },
            {
                "text": "Dispatcher reports leaving urgent cases unassigned overnight.",
                "refs": ["dispatcher"],
                "basis": "stakeholder-report",
            },
            {
                "text": "3 of 7 eligible urgent cases are confirmed deadline misses.",
                "refs": ["events.csv"],
                "basis": "computed",
            },
        ],
        "competing_hypotheses": [
            {
                "text": "Fictional reading: overnight backlog explains unassigned cases.",
                "refs": ["dispatcher", "events.csv"],
                "status": "hypothesis",
            },
            {
                "text": "Fictional reading: same-day acknowledgment still misses the 4-hour deadline.",
                "refs": ["dispatcher", "case-002"],
                "status": "hypothesis",
            },
        ],
        "unresolved_questions": [
            "Do the incomplete windows of case-005 and case-006 hide further misses?",
            "What source event explains the case-008 ordering anomaly?",
        ],
        "diagnostic_experiments": [
            {
                "text": "Extend observation windows for late-day cases, then recompute.",
                "refs": ["events.csv"],
            },
        ],
        "provisional_recommendation": {
            "text": "Fictional suggestion: review overnight assignment coverage. No change without approval.",
            "refs": ["events.csv", "dispatcher"],
            "requires_human_approval": True,
            "executes_production_change": False,
        },
        "counter_evidence": [
            {"text": "case-001 met both deadlines, so the path can work.", "refs": ["case-001"]},
        ],
        "metrics": {"Confirmed deadline misses": 3, "Eligible urgent cases": 7},
    }


class AdapterConfigTest(unittest.TestCase):
    def test_standard_mode_and_model_pinned(self):
        config = MetaConfig()
        self.assertEqual((config.model, config.mode), (MODEL_ID, "standard"))
        with self.assertRaises(ValueError):
            MetaConfig(model="other-model")
        with self.assertRaises(ValueError):
            MetaConfig(mode="turbo")

    def test_absent_credentials_fail_safely(self):
        from backend.meta_adapter import LEGACY_CREDENTIAL_ENV_VAR

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(CREDENTIAL_ENV_VAR, None)
            os.environ.pop(LEGACY_CREDENTIAL_ENV_VAR, None)
            adapter = MetaModelAdapter(MetaConfig(endpoint="http://127.0.0.1:9/unreachable"))
            with self.assertRaises(MissingCredentialsError):
                adapter.request_structured({"prompt": "anything"})

    def test_provider_failure_raises(self):
        adapter = MetaModelAdapter(MetaConfig(endpoint="http://127.0.0.1:9/unreachable"), api_key="fictional-key")
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            with self.assertRaises(ProviderError):
                adapter.request_structured({"prompt": "anything"})

    def test_non_json_response_rejected(self):
        adapter = MetaModelAdapter(MetaConfig(endpoint="http://127.0.0.1:9/x"), api_key="fictional-key")
        fake = mock.MagicMock()
        fake.read.return_value = b"not json"
        fake.__enter__.return_value = fake
        with mock.patch("urllib.request.urlopen", return_value=fake):
            with self.assertRaises(MalformedResponseError):
                adapter.request_structured({"prompt": "anything"})


class InvestigationValidationTest(unittest.TestCase):
    def setUp(self):
        self.report = build_case_report(ROOT)
        self.registry = build_evidence_registry(self.report)

    def test_valid_mock_investigation_passes(self):
        result = produce_investigation(MockAdapter(valid_payload()), ROOT)
        self.assertEqual(result["case_id"], "case-001")
        self.assertIn("human approval", result["note"].lower())

    def test_context_uses_only_verified_quotes_and_computed_numbers(self):
        adapter = MockAdapter(valid_payload())
        produce_investigation(adapter, ROOT)
        context = adapter.last_context
        documents = load_case_documents(ROOT)
        for group in ("policy_requirements", "dispatcher_statements", "manager_statements"):
            for q in context[group]:
                verified = verify_quote(documents, q["doc_id"], q["quote"])
                self.assertEqual((verified.start, verified.end), (q["start"], q["end"]))
        labels = {c["label"]: c["value"] for c in context["calculations"]}
        self.assertEqual((labels["Eligible urgent cases"], labels["Confirmed deadline misses"]), (7, 3))

    def test_malformed_json_rejected(self):
        class RawAdapter:
            def request_structured(self, context, instructions=None):
                return "{bad json"

        with self.assertRaises(MalformedResponseError):
            produce_investigation(RawAdapter(), ROOT)

    def test_missing_citations_rejected(self):
        bad = valid_payload()
        bad["observations"] = [{"text": "Something happened.", "refs": [], "basis": "computed"}]
        with self.assertRaises(InvestigationValidationError):
            validate_investigation(bad, self.registry)

    def test_incorrect_reference_rejected(self):
        bad = valid_payload()
        bad["observations"][0]["refs"] = ["case-999"]
        with self.assertRaises(InvestigationValidationError):
            validate_investigation(bad, self.registry)

    def test_unsupported_conclusion_rejected(self):
        bad = valid_payload()
        bad["observations"][0]["status"] = "validated conclusion"
        with self.assertRaises(InvestigationValidationError):
            validate_investigation(bad, self.registry)

        bad = valid_payload()
        bad["metrics"] = {"Confirmed deadline misses": 99}
        with self.assertRaises(InvestigationValidationError):
            validate_investigation(bad, self.registry)

    def test_stakeholder_report_not_verified_behavior(self):
        bad = valid_payload()
        bad["observations"][1]["basis"] = "verified-quote"
        with self.assertRaises(InvestigationValidationError):
            validate_investigation(bad, self.registry)

    def test_recommendation_needs_human_approval(self):
        bad = valid_payload()
        bad["provisional_recommendation"]["requires_human_approval"] = False
        with self.assertRaises(InvestigationValidationError):
            validate_investigation(bad, self.registry)
        bad = valid_payload()
        bad["provisional_recommendation"]["executes_production_change"] = True
        with self.assertRaises(InvestigationValidationError):
            validate_investigation(bad, self.registry)

    def test_printer_stays_irrelevant(self):
        bad = valid_payload()
        bad["competing_hypotheses"].append(
            {"text": "The printer jam caused the referral delays.", "refs": ["manager"], "status": "hypothesis"}
        )
        with self.assertRaises(InvestigationValidationError):
            validate_investigation(bad, self.registry)
        bad = valid_payload()
        bad["provisional_recommendation"]["text"] = "Fix the printer to fix referrals."
        with self.assertRaises(InvestigationValidationError):
            validate_investigation(bad, self.registry)

    def test_claim_levels_distinct(self):
        self.assertEqual(classify_claim({"refs": ["policy", "events.csv"]}, self.registry), "supported finding")
        self.assertEqual(
            classify_claim({"refs": ["dispatcher"], "status": "hypothesis"}, self.registry), "hypothesis"
        )
        self.assertEqual(classify_claim({"refs": ["events.csv"]}, self.registry), "observation")


if __name__ == "__main__":
    unittest.main()
