"""Task 002 tests: source-verifiable Truth Map for case-001. Stdlib unittest only."""

import csv
import unittest
from pathlib import Path

from backend.events import compute_summary, ordering_anomaly, parse_events_csv
from backend.evidence import (
    COMPUTED_BEHAVIOR,
    INTERPRETATION,
    IRRELEVANT_SYMPTOM_QUOTE,
    POLICY_CLAIM,
    STAKEHOLDER_REPORT,
    computed_behavior,
    interpretation,
    policy_claim,
    stakeholder_report,
)
from backend.quotes import QuoteVerificationError, load_case_documents, verify_quote

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "fixtures" / "case-001" / "events.csv"

POLICY_ASSIGN = "All URGENT referrals must be assigned to a coordinator within 1 hour of creation."
POLICY_ACK = "All URGENT referrals must receive a recorded acknowledgment within 4 hours of creation."
POLICY_WINDOW = "An observation window that closes before the 4-hour deadline is incomplete and cannot prove a miss."
DISPATCHER_BACKLOG = "When the queue spikes, we leave some urgent cases unassigned overnight."
MANAGER_NEVER_WAITS = "No urgent case ever waits unassigned."
MANAGER_DASHBOARD = "The dashboard shows 100% on-time acknowledgment for urgent cases."


class QuotationTest(unittest.TestCase):
    def setUp(self):
        self.docs = load_case_documents(ROOT)

    def test_exact_quotes_verify_with_offsets(self):
        v = verify_quote(self.docs, "policy", POLICY_ACK)
        self.assertEqual((v.doc_id, v.quote), ("policy", POLICY_ACK))
        self.assertEqual(self.docs["policy"].text[v.start : v.end], POLICY_ACK)

    def test_altered_quotation_rejected(self):
        altered = POLICY_ACK.replace("4 hours", "four hours")
        with self.assertRaises(QuoteVerificationError):
            verify_quote(self.docs, "policy", altered)

    def test_invented_quotation_rejected(self):
        with self.assertRaises(QuoteVerificationError):
            verify_quote(self.docs, "policy", "All URGENT referrals are handled by AI instantly.")

    def test_quote_from_wrong_document_rejected(self):
        with self.assertRaises(QuoteVerificationError):
            verify_quote(self.docs, "manager", POLICY_ACK)

    def test_disagreement_quotes_all_verify(self):
        for doc_id, quote in [
            ("policy", POLICY_ASSIGN),
            ("dispatcher", DISPATCHER_BACKLOG),
            ("manager", MANAGER_NEVER_WAITS),
        ]:
            with self.subTest(doc_id=doc_id):
                v = verify_quote(self.docs, doc_id, quote)
                self.assertEqual(v.excerpt(self.docs), quote)


class CalculationTest(unittest.TestCase):
    def setUp(self):
        self.events = parse_events_csv(CSV_PATH)
        self.summary = compute_summary(self.events)

    def test_all_numbers_come_from_csv(self):
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 8)
        self.assertEqual(len(self.events), 8)
        self.assertEqual(self.summary.total_eligible_urgent, 7)

    def test_calculation_correctness(self):
        s = self.summary
        self.assertEqual(s.total_eligible_urgent, 7)
        self.assertEqual(s.assigned_urgent, 5)
        self.assertEqual(s.ack_within_deadline, 1)
        self.assertEqual(s.lacking_ack_within_deadline, 4)
        self.assertEqual(s.incomplete_windows, 2)
        self.assertEqual(set(s.within_ids), {"case-001"})
        self.assertEqual(set(s.lacking_ids), {"case-002", "case-003", "case-004", "case-008"})
        self.assertEqual(set(s.incomplete_ids), {"case-005", "case-006"})

    def test_event_ordering_anomaly_flagged(self):
        by_id = {e.case_id: e for e in self.events}
        self.assertTrue(ordering_anomaly(by_id["case-008"]))
        self.assertFalse(ordering_anomaly(by_id["case-001"]))
        self.assertIn("case-008", self.summary.ordering_anomalies)
        self.assertNotIn("case-008", self.summary.within_ids)

    def test_missing_ack_with_complete_window_is_lacking(self):
        self.assertIn("case-003", self.summary.lacking_ids)
        self.assertIn("case-004", self.summary.lacking_ids)

    def test_incomplete_windows_excluded_from_lacking(self):
        for cid in ("case-005", "case-006"):
            self.assertIn(cid, self.summary.incomplete_ids)
            self.assertNotIn(cid, self.summary.lacking_ids)
            self.assertNotIn(cid, self.summary.within_ids)

    def test_routine_case_excluded(self):
        ids = list(self.summary.within_ids) + list(self.summary.lacking_ids) + list(self.summary.incomplete_ids)
        self.assertNotIn("case-007", ids)


class EvidenceLayerTest(unittest.TestCase):
    def test_layers_stay_distinct(self):
        docs = load_case_documents(ROOT)
        v = verify_quote(docs, "policy", POLICY_ACK)
        item = policy_claim(v.quote, v.doc_id, v.start, v.end)
        comp = computed_behavior("1 of 7 eligible urgent cases acknowledged within 4 hours.", "ack <= created + 4h")
        hyp = interpretation("Fictional reading: overnight backlog explains unassigned urgent cases.", ["dispatcher", "events.csv"])
        self.assertEqual(item.layer, POLICY_CLAIM)
        self.assertEqual(comp.layer, COMPUTED_BEHAVIOR)
        self.assertEqual(hyp.layer, INTERPRETATION)
        self.assertNotEqual(item.layer, comp.layer)

    def test_irrelevant_symptom_recorded_but_not_causal(self):
        docs = load_case_documents(ROOT)
        v = verify_quote(docs, "manager", IRRELEVANT_SYMPTOM_QUOTE)
        item = stakeholder_report(v.quote, v.doc_id, v.start, v.end, causal_relevance=False)
        self.assertEqual(item.layer, STAKEHOLDER_REPORT)
        self.assertFalse(item.causal_relevance)
        summary = compute_summary(parse_events_csv(CSV_PATH))
        blob = " ".join([*summary.within_ids, *summary.lacking_ids, *summary.incomplete_ids])
        self.assertNotIn("printer", blob)
        with open(CSV_PATH, encoding="utf-8") as f:
            header = f.readline().lower()
        self.assertNotIn("printer", header)


if __name__ == "__main__":
    unittest.main()
