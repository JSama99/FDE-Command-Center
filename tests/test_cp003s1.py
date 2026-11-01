"""CP-003.S1: clarity and orientation regression tests.

Frontend-only changes: outcome lines, synthetic display labels,
orientation strips. No backend, evidence, or contract changes.
"""

import re
import unittest
from pathlib import Path

from backend.server import handle_request, new_context

try:
    from test_mission_control import exec_frontend
except ModuleNotFoundError:
    from tests.test_mission_control import exec_frontend

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend" / "control.html").read_text()
JS = (ROOT / "frontend" / "control.js").read_text()
CSS = (ROOT / "frontend" / "control.css").read_text()


def decided_mission(case):
    from backend.experiment import (build_registry, lock_prediction,
                                    reveal_outcome)
    from backend.mission import (choose_diagnostic, decide_intervention,
                                 intervention_proposal, mission_view)
    from backend.experiment import assess

    ctx = new_context()
    registry = build_registry(ctx["base_dir"])
    choose_diagnostic(ctx, "feed-probe")
    lock_prediction(ctx["experiment"], {
        "hypothesis_id": "H-ACK", "expected_finding": "ack-found",
        "expected_observation": "o", "criteria": "c",
        "refs": ["case-003", "events.csv"]}, registry, 0)
    reveal_outcome(ctx["experiment"], 0)
    assessment = assess(ctx["experiment"])
    proposal = intervention_proposal(ctx)
    decide_intervention(ctx, "approve", "note",
                        proposal_id=proposal["proposal_id"],
                        proposal_version=proposal["version"])
    return mission_view(ctx), proposal, assessment


class OutcomeLineTest(unittest.TestCase):
    def test_supported_never_reads_as_solved(self):
        mission, _, assessment = decided_mission(self)
        out = exec_frontend(self, [], mission)
        self.assertEqual(assessment["result"], "supported")
        self.assertIn("Plain terms:", out["roomCards"])
        self.assertIn("not proof of the root cause", out["roomCards"])
        self.assertIn("nothing is fixed", out["roomCards"])
        self.assertNotIn("solved", out["roomCards"].lower())

    def test_competing_hypotheses_stay_unresolved(self):
        mission, _, _ = decided_mission(self)
        out = exec_frontend(self, [{"select-hyp": "H-ACK"}], mission)
        self.assertIn("H-ACK", out["lab"])
        self.assertIn("H-QUEUE", out["lab"])
        self.assertIn("unverified", out["lab"])
        self.assertIn("not proof", out["lab"])

    def test_approval_not_shown_as_execution(self):
        mission, _, _ = decided_mission(self)
        out = exec_frontend(self, [], mission)
        self.assertIn("not an execution", out["roomCards"])
        self.assertIn("nothing runs in production", out["roomCards"])


class SyntheticLabelTest(unittest.TestCase):
    def test_recovery_status_names_synthetic(self):
        mission, _, _ = decided_mission(self)
        out = exec_frontend(self, [{"chaos-tab": "recovery"}], mission,
                            chaos_dir="frontend/chaos-results")
        self.assertIn("checks passed (synthetic)", out["recoveryRecords"])
        self.assertIn("not tested", out["recoveryRecords"])
        self.assertNotIn(">verified<", out["recoveryRecords"])

    def test_missing_evidence_not_a_confirmed_failure(self):
        mission, _, _ = decided_mission(self)
        out = exec_frontend(self, [], mission)
        self.assertIn("not a confirmed miss", out["list"])


class OrientationTest(unittest.TestCase):
    VIEWS = ("view-overview", "view-investigation", "view-hypothesis",
             "view-decision", "view-chaos")

    def test_each_workspace_has_orientation_strip(self):
        for view in self.VIEWS:
            section = re.search(
                rf'<section[^>]*id="{view}"[^>]*>(.*?)</section>', HTML,
                re.S)
            self.assertIsNotNone(section, msg=view)
            strip = re.search(r'<p class="orient">(.*?)</p>',
                              section.group(1), re.S)
            self.assertIsNotNone(strip, msg=view)
            text = strip.group(1)
            self.assertIn("Establishes", text, msg=view)
            self.assertTrue("Next:" in text or "next" in text.lower(),
                            msg=view)

    def test_strips_match_capabilities(self):
        self.assertIn("locks predictions", HTML)
        self.assertIn("never a finding about a real system", HTML)
        self.assertIn("execution happens nowhere", HTML)
        self.assertIn(".orient", CSS)


if __name__ == "__main__":
    unittest.main()
