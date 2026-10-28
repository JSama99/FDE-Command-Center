"""Task 009: integrated field-mission tests. Offline only, no model calls."""

import json
import unittest
from pathlib import Path

from backend.server import handle_request, new_context


def call(ctx, method, target, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    status, data, _ = handle_request(method, target, body, ctx)
    return status, data


PREDICT = {
    "hypothesis_id": "H-ACK",
    "expected_finding": "ack-found",
    "expected_observation": "The source log holds a case-003 acknowledgment missing from the feed.",
    "criteria": "ack-found supports H-ACK; no-ack supports H-QUEUE for the assigned class.",
    "refs": ["case-003", "events.csv"],
}


def decide(ctx, decision, note="Test rationale: deterministic walkthrough decision."):
    """Decide on the currently shown proposal (proposal-to-decision binding)."""
    status, proposal = call(ctx, "GET", "/api/mission/proposal")
    assert status == 200, proposal
    return call(ctx, "POST", "/api/mission/intervention", {
        "decision": decision, "note": note,
        "proposal_id": proposal["proposal_id"],
        "proposal_version": proposal["version"],
    })


class MissionViewTest(unittest.TestCase):
    def test_view_has_all_mission_elements(self):
        ctx = new_context()
        status, data = call(ctx, "GET", "/api/mission")
        self.assertEqual(status, 200)
        for key in ("brief", "constraint", "evidence", "hypotheses",
                    "diagnostics", "experiment", "stages", "glossary",
                    "fictional_notice"):
            self.assertIn(key, data)
        self.assertEqual(len(data["diagnostics"]), 2)
        self.assertTrue(data["constraint"])
        self.assertTrue(data["evidence"]["calculations"])
        self.assertIn("customer engagement", data["fictional_notice"].lower()
                      or "not a customer" in data["fictional_notice"].lower())


class FeedProbePathTest(unittest.TestCase):
    def run_path(self, decision="approve"):
        ctx = new_context()
        self.assertEqual(call(ctx, "POST", "/api/mission/diagnostic",
                              {"choice": "feed-probe"})[0], 200)
        status, data = call(ctx, "GET", "/api/mission/diagnostic/result")
        self.assertEqual(status, 200)
        self.assertTrue(data["requires_prediction"])
        self.assertEqual(call(ctx, "POST", "/api/experiment/predict", PREDICT)[0], 200)
        self.assertEqual(call(ctx, "POST", "/api/experiment/reveal", {})[0], 200)
        self.assertEqual(call(ctx, "POST", "/api/experiment/assess", {})[0], 200)
        status, data = decide(ctx, decision, "test note")
        self.assertEqual(status, 200)
        self.assertFalse(data["executed"])
        status, report = call(ctx, "GET", "/api/mission/report")
        self.assertEqual(status, 200)
        return ctx, report

    def test_full_feed_probe_mission(self):
        _, report = self.run_path("approve")
        self.assertEqual(report["diagnostic"], "feed-probe")
        self.assertEqual(report["intervention"]["decision"], "approve")
        self.assertFalse(report["intervention"]["executed"])
        self.assertIsNotNone(report["prediction"])
        self.assertIsNotNone(report["assessment"])
        self.assertTrue(report["what_was_learned"])
        self.assertTrue(report["unresolved"])
        self.assertIn("fictional", report["fictional_notice"].lower())

    def test_defer_path(self):
        _, report = self.run_path("defer")
        self.assertEqual(report["intervention"]["decision"], "defer")


class TimestampAuditPathTest(unittest.TestCase):
    def test_full_audit_mission(self):
        ctx = new_context()
        self.assertEqual(call(ctx, "POST", "/api/mission/diagnostic",
                              {"choice": "timestamp-audit"})[0], 200)
        status, data = call(ctx, "GET", "/api/mission/diagnostic/result")
        self.assertEqual(status, 200)
        self.assertFalse(data["requires_prediction"])
        self.assertIn("5 of 7", data["finding"])
        self.assertEqual(data["numbers"]["assigned_within_1h"]["value"], 5)
        self.assertEqual(decide(ctx, "reject")[0], 200)
        status, report = call(ctx, "GET", "/api/mission/report")
        self.assertEqual(status, 200)
        self.assertEqual(report["diagnostic"], "timestamp-audit")
        self.assertIsNone(report["prediction"])
        self.assertTrue(report["what_was_learned"])


class InvalidTransitionTest(unittest.TestCase):
    def test_result_before_choice(self):
        ctx = new_context()
        self.assertEqual(call(ctx, "GET", "/api/mission/diagnostic/result")[0], 409)

    def test_diagnostic_cannot_change(self):
        ctx = new_context()
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "timestamp-audit"})
        self.assertEqual(call(ctx, "POST", "/api/mission/diagnostic",
                              {"choice": "feed-probe"})[0], 409)

    def test_unknown_diagnostic(self):
        ctx = new_context()
        self.assertEqual(call(ctx, "POST", "/api/mission/diagnostic",
                              {"choice": "nope"})[0], 400)

    def test_choice_after_lock_too_late(self):
        ctx = new_context()
        call(ctx, "POST", "/api/experiment/predict", PREDICT)
        self.assertEqual(call(ctx, "POST", "/api/mission/diagnostic",
                              {"choice": "feed-probe"})[0], 409)

    def test_intervention_too_early(self):
        ctx = new_context()
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        self.assertEqual(call(ctx, "POST", "/api/mission/intervention",
                              {"decision": "approve"})[0], 409)

    def test_report_before_decision(self):
        ctx = new_context()
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "timestamp-audit"})
        call(ctx, "GET", "/api/mission/diagnostic/result")
        self.assertEqual(call(ctx, "GET", "/api/mission/report")[0], 409)

    def test_double_decision_rejected(self):
        ctx = new_context()
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "timestamp-audit"})
        call(ctx, "GET", "/api/mission/diagnostic/result")
        decide(ctx, "defer")
        self.assertEqual(call(ctx, "POST", "/api/mission/intervention",
                              {"decision": "approve"})[0], 409)

    def test_bad_decision(self):
        ctx = new_context()
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "timestamp-audit"})
        call(ctx, "GET", "/api/mission/diagnostic/result")
        self.assertEqual(call(ctx, "POST", "/api/mission/intervention",
                              {"decision": "maybe"})[0], 400)


class EvidenceIntegrityTest(unittest.TestCase):
    def test_report_numbers_match_backend(self):
        from backend.report import build_case_report

        ctx = new_context()
        status, data = call(ctx, "GET", "/api/mission")
        expected = build_case_report(ctx["base_dir"])["calculations"]
        self.assertEqual(data["evidence"]["calculations"], expected)

    def test_locked_prediction_preserved_into_report(self):
        ctx = new_context()
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        _, locked = call(ctx, "POST", "/api/experiment/predict", PREDICT)
        call(ctx, "POST", "/api/experiment/reveal", {})
        call(ctx, "POST", "/api/experiment/assess", {})
        decide(ctx, "approve")
        _, report = call(ctx, "GET", "/api/mission/report")
        self.assertEqual(report["prediction"]["hash"], locked["prediction"]["hash"])
        self.assertEqual(report["prediction"]["expected_observation"],
                         PREDICT["expected_observation"])


class BrowserWiringTest(unittest.TestCase):
    """Static browser-workflow verification: every control the JS touches
    exists in the page, and every API call the page makes has a server route."""

    def test_all_js_element_ids_exist_in_page(self):
        import re

        html = (Path(__file__).resolve().parents[1] / "frontend" / "mission.html").read_text()
        js = (Path(__file__).resolve().parents[1] / "frontend" / "mission.js").read_text()
        # IDs exist statically in the page or are created by the JS itself.
        known_ids = set(re.findall(r'id="([^"]+)"', html + js))
        for element_id in set(re.findall(r'getElementById\("([^"]+)"\)', js)):
            self.assertIn(element_id, known_ids, msg=element_id)

    def test_all_js_api_calls_have_server_routes(self):
        import re

        root = Path(__file__).resolve().parents[1]
        js = (root / "frontend" / "mission.js").read_text()
        server = (root / "backend" / "server.py").read_text()
        routes = set(re.findall(r'path == "([^"]+)"', server))
        for url in set(re.findall(r'["\'](/api/[^"\']+)["\']', js)):
            path = url.split("?")[0]
            self.assertIn(path, routes, msg=url)

    def test_page_scripts_load_with_javascript_mime(self):
        """Browser simulation for the Safari failure: load each page, resolve
        every script src the way a browser would, and require HTTP 200 with
        a JavaScript Content-Type. Covers both /page.html and
        /frontend/page.html entry URLs."""
        import re
        import urllib.parse

        for page_url in ("/", "/mission.html", "/investigate.html",
                         "/frontend/mission.html", "/frontend/investigate.html"):
            status, data, _ = handle_request("GET", page_url, None, new_context())
            self.assertEqual(status, 200, msg=page_url)
            if isinstance(data, bytes):
                for src in re.findall(r'<script src="([^"]+)"', data.decode("utf-8")):
                    script_url = urllib.parse.urljoin(page_url, src)
                    status, payload, content_type = handle_request(
                        "GET", urllib.parse.urlparse(script_url).path,
                        None, new_context())
                    self.assertEqual(status, 200, msg=f"{page_url} -> {src}")
                    self.assertIn("javascript", content_type,
                                  msg=f"{page_url} -> {src}")

    def test_no_unwired_buttons(self):
        import re

        js = (Path(__file__).resolve().parents[1] / "frontend" / "mission.js").read_text()
        wired = set(re.findall(r'getElementById\("(\w+Btn)"\)', js))
        self.assertTrue({"approveBtn", "rejectBtn", "deferBtn", "mockBtn",
                         "liveBtn", "reportBtn"}.issubset(wired))


if __name__ == "__main__":
    unittest.main()
