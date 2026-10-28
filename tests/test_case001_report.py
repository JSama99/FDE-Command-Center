"""Task 003 tests: strict categories and backend-generated report. Stdlib unittest only."""

import json
import unittest
from pathlib import Path

from backend.events import parse_events_csv
from backend.report import build_case_report
from backend.report_categories import categorize

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "fixtures" / "case-001" / "events.csv"
HTML_PATH = ROOT / "frontend" / "case-001.html"
JSON_PATH = ROOT / "frontend" / "case-001.json"


class CategorySeparationTest(unittest.TestCase):
    def setUp(self):
        self.cats = categorize(parse_events_csv(CSV_PATH))

    def test_partition_is_disjoint_and_complete(self):
        c = self.cats
        self.assertEqual(
            sorted(c["valid_ack_within_4h"] + c["confirmed_miss"] + c["anomalous"] + c["incomplete"]),
            sorted(c["eligible"]),
        )
        self.assertEqual(len(c["eligible"]), 7)

    def test_anomalous_and_incomplete_are_never_confirmed(self):
        c = self.cats
        for cid in c["anomalous"] + c["incomplete"]:
            self.assertNotIn(cid, c["confirmed_miss"])

    def test_one_hour_assignment_compliance(self):
        c = self.cats
        self.assertEqual(len(c["with_assignment"]), 5)
        self.assertEqual(len(c["assigned_within_1h"]), 5)
        self.assertEqual(c["assigned_late"], [])
        self.assertEqual(set(c["assigned_within_1h"]), {"case-001", "case-002", "case-003", "case-005", "case-008"})

    def test_confirmed_misses_need_complete_windows(self):
        c = self.cats
        self.assertEqual(set(c["confirmed_miss"]), {"case-002", "case-003", "case-004"})
        self.assertNotIn("case-008", c["confirmed_miss"])
        self.assertNotIn("case-005", c["confirmed_miss"])

    def test_missing_and_incomplete_evidence(self):
        c = self.cats
        self.assertIn("case-003", c["confirmed_miss"])
        self.assertIn("case-004", c["confirmed_miss"])
        self.assertEqual(set(c["incomplete"]), {"case-005", "case-006"})


class SourceBackedRenderingTest(unittest.TestCase):
    def setUp(self):
        self.report = build_case_report(ROOT)
        self.html = HTML_PATH.read_text(encoding="utf-8")
        self.data = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    def test_report_matches_backend_builder(self):
        self.assertEqual(self.data["categories"], self.report["categories"])
        self.assertEqual(self.data["calculations"], self.report["calculations"])

    def test_every_number_is_traceable(self):
        for calc in self.data["calculations"]:
            self.assertTrue(calc["rule"])
            self.assertEqual(calc["source"], "fixtures/case-001/events.csv")
            self.assertIn(str(calc["value"]), self.html)
        for quote in self.data["policy_requirements"]:
            self.assertIn(quote["quote"], self.html)
            self.assertIn(quote["doc_id"], self.html)
            self.assertIn(f"[{quote['start']}:{quote['end']}]", self.html)

    def test_statements_attributed_and_printer_not_causal(self):
        self.assertIn("dispatcher", self.html)
        self.assertIn("manager", self.html)
        self.assertIn("Reported observation (not a cause)", self.html)
        obs = self.data["reported_observation_only"]
        self.assertFalse(obs["causal_relevance"])
        self.assertIn(obs["quote"], self.html)

    def test_no_unsupported_causal_conclusions(self):
        lowered = self.html.lower()
        self.assertNotIn("caused by", lowered)
        self.assertNotIn("proven", lowered)
        self.assertIn("unverified interpretation", lowered)
        for h in self.data["hypotheses"]:
            self.assertEqual(h["status"], "unverified interpretation")
            self.assertIn(h["text"], self.html)


if __name__ == "__main__":
    unittest.main()
