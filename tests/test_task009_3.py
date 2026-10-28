"""Task 009.3: Liquid Glass shell, rationale hardening, safeguards. Offline only."""

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


def ready_feed_probe(ctx, payload=PREDICT):
    call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
    call(ctx, "POST", "/api/experiment/predict", payload)
    call(ctx, "POST", "/api/experiment/reveal", {})
    call(ctx, "POST", "/api/experiment/assess", {})
    return ctx


ROOT = Path(__file__).resolve().parents[1]


class RationaleHardeningTest(unittest.TestCase):
    def bound_decide(self, ctx, note):
        _, proposal = call(ctx, "GET", "/api/mission/proposal")
        return call(ctx, "POST", "/api/mission/intervention", {
            "decision": "approve", "note": note,
            "proposal_id": proposal["proposal_id"],
            "proposal_version": proposal["version"]})

    def ready_audit(self):
        ctx = new_context()
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "timestamp-audit"})
        call(ctx, "GET", "/api/mission/diagnostic/result")
        return ctx

    def test_placeholder_rationales_rejected(self):
        for note in ("false", "True", "n/a", "N/A", "none", "...", "!!!", " - - "):
            ctx = self.ready_audit()
            status, data = self.bound_decide(ctx, note)
            self.assertEqual(status, 400, msg=note)
            self.assertEqual(data["error"], "placeholder-rationale", msg=note)

    def test_genuine_rationale_accepted(self):
        ctx = self.ready_audit()
        status, _ = self.bound_decide(ctx, "Coverage gap is minor; monitor one cycle.")
        self.assertEqual(status, 200)


class WorkspaceShellTest(unittest.TestCase):
    def test_five_workspaces_with_button_navigation(self):
        html = (ROOT / "frontend" / "mission.html").read_text()
        for workspace in ("ws-overview", "ws-evidence", "ws-diagnostics",
                          "ws-decision", "ws-report"):
            self.assertIn(f'id="{workspace}"', html)
            self.assertIn(f'data-ws="{workspace}"', html)
        nav_buttons = re.findall(r"<button[^>]*data-ws=", html)
        self.assertGreaterEqual(len(nav_buttons), 10)  # sidebar + compact topnav
        self.assertIn("aria-current", html)

    def test_persistent_simulation_indicator(self):
        html = (ROOT / "frontend" / "mission.html").read_text()
        self.assertIn("Simulation", html)
        self.assertIn("No production actions", html)
        self.assertIn("fictional", html.lower())

    def test_stylesheet_loads_with_css_mime(self):
        status, _, content_type = handle_request("GET", "/mission.css", None, new_context())
        self.assertEqual(status, 200)
        self.assertIn("css", content_type)

    def test_design_tokens_present(self):
        css = (ROOT / "frontend" / "mission.css").read_text()
        for token in ("backdrop-filter", "prefers-reduced-motion",
                      "focus-visible", "@media", "--cyan", "--gold"):
            self.assertIn(token, css, msg=token)


class SafeguardTest(unittest.TestCase):
    def test_withheld_outcome_concealed_before_lock(self):
        ctx = new_context()
        _, view = call(ctx, "GET", "/api/mission")
        blob = json.dumps(view)
        self.assertNotIn("SRC-FEED-GAP", blob)
        self.assertNotIn("09:40", blob)
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        _, result = call(ctx, "GET", "/api/mission/diagnostic/result")
        blob = json.dumps(result)
        self.assertNotIn("SRC-FEED-GAP", blob)
        self.assertNotIn("09:40", blob)

    def test_completed_stages_read_only(self):
        js = (ROOT / "frontend" / "mission.js").read_text()
        self.assertIn("read-only", js)
        ctx = ready_feed_probe(new_context())
        decide(ctx, "approve", "Bounded and read-only.")
        _, view = call(ctx, "GET", "/api/mission")
        stages = {s["stage"]: s["state"] for s in view["stages"]}
        self.assertEqual(view["mission"]["intervention"]["decision"], "approve")

    def test_binding_and_paths_intact(self):
        ctx = ready_feed_probe(new_context())
        _, proposal = call(ctx, "GET", "/api/mission/proposal")
        self.assertEqual(proposal["proposal_id"], "PROP-002")
        ctx2 = new_context()
        call(ctx2, "POST", "/api/mission/diagnostic", {"choice": "timestamp-audit"})
        call(ctx2, "GET", "/api/mission/diagnostic/result")
        _, proposal2 = call(ctx2, "GET", "/api/mission/proposal")
        self.assertEqual(proposal2["proposal_id"], "PROP-003")

    def test_report_renders_thirteen_sections(self):
        ctx = ready_feed_probe(new_context())
        decide(ctx, "approve", "Bounded and read-only.")
        _, report = call(ctx, "GET", "/api/mission/report")
        self.assertEqual(len(report["readable_sections"]), 13)
        js = (ROOT / "frontend" / "mission.js").read_text()
        self.assertIn("readable_sections", js)
        self.assertNotIn("JSON.stringify(v)", js)

    def test_full_mission_without_network(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network used")):
            ctx = ready_feed_probe(new_context())
            self.assertEqual(decide(ctx, "approve", "Offline walkthrough.")[0], 200)
            self.assertEqual(call(ctx, "GET", "/api/mission/report")[0], 200)


if __name__ == "__main__":
    unittest.main()
