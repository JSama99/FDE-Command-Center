"""Task 009.3a: Liquid Glass visual refinement. Presentation only; offline."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class OverviewConsoleTest(unittest.TestCase):
    def test_overview_structure(self):
        html = (ROOT / "frontend" / "mission.html").read_text()
        for element_id in ("missionStatus", "heroMetrics", "timeline",
                           "brief", "steps", "hypotheses", "glossary"):
            self.assertIn(f'id="{element_id}"', html)

    def test_glossary_collapsible_and_brief_prose(self):
        html = (ROOT / "frontend" / "mission.html").read_text()
        self.assertIn("<details", html)
        self.assertIn('class="prose"', html)

    def test_hero_and_timeline_wired(self):
        js = (ROOT / "frontend" / "mission.js").read_text()
        for token in ("heroMetrics", "missionStatus", "timeline",
                      "Eligible urgent cases", "Confirmed deadline misses",
                      "Valid acknowledgment within 4 hours",
                      "hyp-hack", "hyp-hqueue", "Full mission brief"):
            self.assertIn(token, js, msg=token)


class DepthAndNavStyleTest(unittest.TestCase):
    def test_depth_tokens(self):
        css = (ROOT / "frontend" / "mission.css").read_text()
        for token in (".panel::before", ".panel.lifted", ".hero .figure",
                      ".timeline li", "details.ref",
                      'button[data-ws="ws-decision"]::before',
                      ".topnav button[aria-current"):
            self.assertIn(token, css, msg=token)

    def test_readability_safeguards_kept(self):
        css = (ROOT / "frontend" / "mission.css").read_text()
        for token in ("backdrop-filter", "@supports", "prefers-reduced-motion",
                      "focus-visible", "@media"):
            self.assertIn(token, css, msg=token)


if __name__ == "__main__":
    unittest.main()
