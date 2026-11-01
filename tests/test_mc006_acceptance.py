"""MC-006: Integrated Mission Control acceptance, Areas A-H.

Offline only. No provider calls, no new endpoints, no persistence
activation, no receipt linkage. Uses handle_request against in-memory
contexts, static frontend inspection, the real chaos modules, and the
existing Node harness driving the real frontend/control.js.
"""

import json
import re
import unittest
from pathlib import Path

from backend.server import handle_request, new_context

try:
    from test_mission_control import exec_frontend
except ModuleNotFoundError:  # invoked as tests.test_mc006_acceptance
    from tests.test_mission_control import exec_frontend

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "frontend" / "control.js").read_text()
HTML = (ROOT / "frontend" / "control.html").read_text()
SERVER_SRC = (ROOT / "backend" / "server.py").read_text()
MARKER = "SRC-FEED-GAP-09:40"
PREDICTION = {
    "hypothesis_id": "H-ACK",
    "expected_finding": "ack-found",
    "expected_observation": "Source log holds a case-003 ack missing from the feed.",
    "criteria": "ack-found supports H-ACK; no-ack supports H-QUEUE.",
    "refs": ["case-003", "events.csv"],
}


def call(ctx, method, target, body=None):
    raw = None if body is None else json.dumps(body).encode("utf-8")
    return handle_request(method, target, raw, ctx)


def mission_snapshot(case):
    ctx = new_context()
    status, mission, _ = call(ctx, "GET", "/api/mission")
    case.assertEqual(status, 200)
    return mission


class AreaANavigationTest(unittest.TestCase):
    """Area A: workspace and tab integrity, no state-changing side effects."""

    def test_all_workspaces_and_chaos_tabs_present(self):
        for view in ("view-overview", "view-investigation", "view-hypothesis",
                     "view-decision", "view-chaos"):
            self.assertIn(f'id="{view}"', HTML, msg=view)
        for tab in ("scenario", "results", "evaluation", "recovery"):
            self.assertIn(f'data-ctab="{tab}"', HTML, msg=tab)

    def test_nav_buttons_match_views(self):
        targets = set(re.findall(r'data-view="([^"]+)"', HTML))
        for target in targets:
            self.assertIn(f'id="{target}"', HTML, msg=target)

    def test_chaos_tab_switching_issues_no_post(self):
        mission = mission_snapshot(self)
        out = exec_frontend(self, [
            {"chaos-tab": "evaluation"},
            {"chaos-tab": "recovery"},
            {"chaos-tab": "results"},
            {"chaos-tab": "scenario"},
        ], mission, chaos_dir="frontend/chaos-results")
        posts = [f for f in out["fetchLog"] if f["method"] != "GET"]
        self.assertEqual(posts, [])
        for panel in ("evalReport", "recoveryRecords"):
            self.assertTrue(out[panel].strip(), msg=panel)

    def test_eval_dashboard_shows_counts_not_bare_ratios(self):
        mission = mission_snapshot(self)
        out = exec_frontend(self, [{"chaos-tab": "evaluation"}], mission,
                            chaos_dir="frontend/chaos-results")
        for token in ("2 of 2", "0 of 2"):
            self.assertIn(token, out["evalReport"], msg=token)
        self.assertIn("Not defined", JS)  # null-guard for zero denominators
        self.assertIn("numer === null", JS)

    def test_no_simulation_runs_on_tab_open(self):
        mission = mission_snapshot(self)
        out = exec_frontend(self, [
            {"select-scn": "CHS-ASSIGN-01"},
            {"select-variant": "injected"},
            {"chaos-tab": "results"},
        ], mission, chaos_dir="frontend/chaos-results")
        runs = [f for f in out["fetchLog"]
                if f["url"] == "/api/chaos/run"]
        self.assertEqual(runs, [])


class AreaBEpistemicsTest(unittest.TestCase):
    """Area B: provenance and classification boundaries."""

    def test_no_endorsed_causal_language_in_graph_data(self):
        for bad in ("caused by", "proves H-", "root cause established"):
            self.assertNotIn(bad, JS, msg=bad)
        # "confirmed failure" occurs only inside an explicit guard.
        self.assertIn("Never a confirmed failure on its own", JS)
        # The single "causes" occurrence is an attributed stakeholder
        # assertion with an explicit non-endorsement disclaimer.
        hits = [line for line in JS.splitlines() if "causes" in line]
        self.assertEqual(len(hits), 1)
        self.assertIn("not an endorsed causal finding", hits[0])

    def test_edge_types_are_non_causal(self):
        edges = re.findall(
            r"\{s:\s*\"([^\"]+)\",\s*t:\s*\"([^\"]+)\",\s*type:\s*\"([^\"]+)\","
            r"\s*status:\s*\"([^\"]+)\"",
            JS)
        self.assertTrue(edges)
        allowed = {"conflicts-with", "measured-against", "computed-from",
                   "asserts", "relevant-to"}
        for src, tgt, kind, status in edges:
            self.assertIn(kind, allowed, msg=f"{src}->{tgt}:{kind}")
            self.assertIn(status, ("verified", "reported", "hypothesized"),
                          msg=f"{src}->{tgt}")
            if kind == "asserts":
                self.assertEqual(status, "reported", msg=f"{src}->{tgt}")
            # Every edge carries source refs and a scoping note.
            self.assertIn("refs:", JS)
            self.assertIn("note:", JS)

    def test_incomplete_window_never_a_confirmed_miss(self):
        mission = mission_snapshot(self)
        labels = {c["label"]: c["value"]
                  for c in mission["evidence"]["calculations"]}
        self.assertEqual(labels["Confirmed deadline misses"], 3)
        self.assertEqual(
            labels["Incomplete windows (insufficient evidence, "
                   "not a confirmed miss)"], 2)
        self.assertEqual(
            labels["Anomalous sequences (needs source check, "
                   "not a confirmed miss)"], 1)
        for hyp in mission["hypotheses"]:
            self.assertEqual(hyp["status"], "unverified interpretation")

    def test_hypotheses_labeled_unverified_in_frontend(self):
        self.assertIn('"unverified hypothesis"', JS)
        self.assertNotIn('"verified hypothesis"', JS)
        self.assertNotIn("'verified hypothesis'", JS)


class AreaCHypothesisPredictionTest(unittest.TestCase):
    """Area C: hypothesis display and withheld-outcome protection."""

    def test_both_hypotheses_visible_without_confidence_scores(self):
        mission = mission_snapshot(self)
        out = exec_frontend(self, [{"select-hyp": "H-ACK"},
                                   {"select-hyp": "H-QUEUE"}], mission)
        self.assertIn("H-ACK", out["lab"])
        self.assertIn("H-QUEUE", out["lab"])
        self.assertIn("No confidence score is assigned", out["lab"])
        self.assertIsNone(re.search(r"\d+%", out["lab"]))

    def test_withheld_outcome_absent_before_reveal(self):
        ctx = new_context()
        for target in ("/api/mission", "/api/mission/proposal",
                       "/api/mission/diagnostic/result", "/api/experiment"):
            status, payload, _ = call(ctx, "GET", target)
            body = json.dumps(payload)
            self.assertNotIn(MARKER, body, msg=target)
            if target in ("/api/mission/proposal",
                           "/api/mission/diagnostic/result"):
                self.assertEqual(status, 409, msg=target)

    def test_reveal_before_lock_rejected_and_still_concealed(self):
        ctx = new_context()
        status, _, _ = call(ctx, "POST", "/api/mission/diagnostic",
                            {"choice": "feed-probe"})
        self.assertEqual(status, 200)
        status, _, _ = call(ctx, "POST", "/api/experiment/reveal", None)
        self.assertEqual(status, 409)
        status, _, _ = call(ctx, "POST", "/api/experiment/predict",
                            PREDICTION)
        self.assertEqual(status, 200)
        status, _, _ = call(ctx, "POST", "/api/experiment/predict",
                            PREDICTION)
        self.assertEqual(status, 409)

    def test_locked_prediction_survives_full_lifecycle(self):
        ctx = new_context()
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        call(ctx, "POST", "/api/experiment/predict", PREDICTION)
        call(ctx, "POST", "/api/experiment/reveal", None)
        status, assessment, _ = call(ctx, "POST", "/api/experiment/assess",
                                    None)
        self.assertEqual(status, 200)
        self.assertIn(assessment["assessment"]["result"],
                      ("supported", "contradicted", "unresolved"))
        self.assertNotIn("verified root cause",
                         json.dumps(assessment).lower())


class AreaDDecisionRoomTest(unittest.TestCase):
    """Area D: read-only Decision Room, no linkage, no execution."""

    def test_decision_room_issues_no_posts(self):
        self.assertNotIn("/api/mission/intervention", JS)
        self.assertNotIn("/api/revision/approve", JS)
        self.assertNotIn("/api/approval", JS)
        fetched = set(re.findall(r'fetch\("([^"]+)"', JS))
        self.assertEqual(fetched, {"/api/mission", "/api/mission/proposal",
                                   "/api/chaos/run"})
        self.assertIn("approval never executes anything", JS)

    def test_no_receipt_route_or_linkage_field(self):
        self.assertNotIn("/api/receipt", SERVER_SRC)
        self.assertNotIn("receipt_link", SERVER_SRC)
        mission = mission_snapshot(self)
        self.assertNotIn("receipt", json.dumps(mission).lower())

    def test_snapshot_store_remains_unwired(self):
        for mod in ("mission_store", "mission_snapshot"):
            self.assertNotIn(f"from .{mod} import", SERVER_SRC, msg=mod)
            self.assertNotIn(f"from backend.{mod} import", SERVER_SRC,
                             msg=mod)

    def test_approved_is_not_executed(self):
        ctx = new_context()
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        call(ctx, "POST", "/api/experiment/predict", PREDICTION)
        call(ctx, "POST", "/api/experiment/reveal", None)
        call(ctx, "POST", "/api/experiment/assess", None)
        status, proposal, _ = call(ctx, "GET", "/api/mission/proposal")
        self.assertEqual(status, 200)
        status, _, _ = call(ctx, "POST", "/api/mission/intervention", {
            "decision": "approve",
            "note": "Bounded feed reconciliation is the smallest reversible step.",
            "proposal_id": proposal["proposal_id"],
            "proposal_version": proposal["version"],
        })
        self.assertEqual(status, 200)
        status, report, _ = call(ctx, "GET", "/api/mission/report")
        self.assertEqual(status, 200)
        body = json.dumps(report)
        self.assertIn("approve", body)
        self.assertNotIn('"executed": true', body)


class AreaEChaosMetricsTest(unittest.TestCase):
    """Area E: evaluation metrics and recovery verification."""

    def test_expected_confusion_and_derived_metrics(self):
        from backend.chaos_evaluation import evaluate
        report = evaluate()
        self.assertEqual(report["confusion"], {
            "true_positives": 2, "false_positives": 0,
            "true_negatives": 2, "false_negatives": 0})
        metrics = report["metrics"]
        self.assertEqual((metrics["precision"],
                          metrics["precision_denominator"]), (1.0, 2))
        self.assertEqual((metrics["recall"],
                          metrics["recall_denominator"]), (1.0, 2))
        self.assertEqual((metrics["false_positive_rate"],
                          metrics["false_positive_rate_denominator"]),
                         (0.0, 2))
        self.assertEqual((metrics["false_negative_rate"],
                          metrics["false_negative_rate_denominator"]),
                         (0.0, 2))
        self.assertEqual(report["indeterminate"], 0)

    def test_safety_unavailable_and_scope_preserved(self):
        from backend.chaos_evaluation import evaluate
        report = evaluate()
        self.assertEqual(report["safety"], {"cases": 2, "correct": 2})
        self.assertTrue(any(u["case"] == "C8-order-anomaly"
                            and "ordering anomaly" in u["reason"]
                            for u in report["unavailable"]))
        self.assertIn("synthetic", report["scope"].lower())
        self.assertEqual(report["overall"], "pass")

    def test_rendered_artifact_matches_production_report(self):
        from backend.chaos_evaluation import evaluate
        artifact = json.loads((ROOT / "frontend" / "chaos-results"
                               / "chaos-eval-report.json").read_text())
        fresh = evaluate()
        self.assertEqual(artifact["confusion"], fresh["confusion"])
        self.assertEqual(artifact["metrics"], fresh["metrics"])
        self.assertEqual(artifact["schema"], "ChaosEvaluationReportV1")

    def test_recovery_statuses_and_regression_checks(self):
        from backend.chaos_recovery import run_recovery_test
        ok_assign = run_recovery_test("CHS-ASSIGN-01", "restore-assignments")
        ok_ack = run_recovery_test("CHS-ACK-01", "reconcile-feed")
        inconclusive = run_recovery_test("CHS-WINDOW-01", "none-available")
        self.assertEqual(ok_assign["status"], "verified")
        self.assertEqual(ok_ack["status"], "verified")
        self.assertEqual(inconclusive["status"], "not-tested")
        for result in (ok_assign, ok_ack):
            self.assertTrue(result["regression"])
            self.assertTrue(result["refs"])
        for name, fresh in (("CHS-ASSIGN-01.recovery.json", ok_assign),
                            ("CHS-ACK-01.recovery.json", ok_ack),
                            ("CHS-WINDOW-01.recovery.json", inconclusive)):
            artifact = json.loads((ROOT / "frontend" / "chaos-results"
                                   / name).read_text())
            self.assertEqual(artifact["status"], fresh["status"])
            self.assertEqual(artifact["schema"], "ChaosRecoveryResultV1")

    def test_zero_denominator_metrics_are_undefined(self):
        from backend.chaos_evaluation import compute_metrics
        metrics = compute_metrics(0, 0, 0, 0)
        self.assertIsNone(metrics["precision"])
        self.assertIsNone(metrics["recall"])


class AreaFArtifactIntegrityTest(unittest.TestCase):
    """Area F: artifact loading, rejection, and safe rendering."""

    ARTIFACTS = ("CHS-ASSIGN-01.baseline.json", "CHS-ASSIGN-01.injected.json",
                 "CHS-ACK-01.baseline.json", "CHS-ACK-01.injected.json",
                 "CHS-WINDOW-01.baseline.json", "CHS-WINDOW-01.injected.json",
                 "chaos-eval-report.json", "CHS-ASSIGN-01.recovery.json",
                 "CHS-ACK-01.recovery.json", "CHS-WINDOW-01.recovery.json")

    def test_only_allowlisted_simulation_results_load(self):
        from backend.chaos_simulation import validate_simulation_result
        for name in self.ARTIFACTS[:6]:
            artifact = json.loads((ROOT / "frontend" / "chaos-results"
                                   / name).read_text())
            checks = validate_simulation_result(artifact)
            self.assertEqual(checks["schema"], "valid")
            self.assertEqual(artifact["recovery"], "not-tested")

    def test_malformed_eval_artifact_rejected_at_display(self):
        import shutil
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "chaos-eval-report.json").write_text('{"schema": "Nope"}')
        for name in ("CHS-ASSIGN-01.recovery.json",
                     "CHS-ACK-01.recovery.json",
                     "CHS-WINDOW-01.recovery.json"):
            shutil.copy(ROOT / "frontend" / "chaos-results" / name, tmp / name)
        mission = mission_snapshot(self)
        out = exec_frontend(self, [{"chaos-tab": "evaluation"}], mission,
                            chaos_dir=str(tmp))
        self.assertNotIn("2 / 2", out["evalReport"])

    def test_missing_artifact_produces_error_state(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        mission = mission_snapshot(self)
        out = exec_frontend(self, [{"chaos-tab": "evaluation"}], mission,
                            chaos_dir=str(tmp))
        self.assertTrue(out["evalReport"].strip())
        self.assertNotIn("2 / 2", out["evalReport"])

    def test_no_arbitrary_artifact_paths_in_frontend(self):
        fetched = re.findall(r'chaos-results/\$\{([^}]+)\}', JS)
        self.assertTrue(fetched)
        for expr in fetched:
            self.assertIn(expr, ("name", "scnId", "file"),
                          msg=f"unexpected artifact path expression: {expr}")


class AreaGSecurityTest(unittest.TestCase):
    """Area G: execution boundaries; no new write surfaces."""

    def test_post_route_inventory_unchanged(self):
        routes = set(re.findall(r'path == "([^"]+)" and method == "POST"',
                                SERVER_SRC))
        expected = {"/api/investigation", "/api/experiment/predict",
                    "/api/experiment/reveal", "/api/experiment/assess",
                    "/api/prediction/generate", "/api/prediction/lock",
                    "/api/revision/generate", "/api/revision/approve",
                    "/api/approval", "/api/mission/diagnostic",
                    "/api/mission/intervention", "/api/chaos/run"}
        self.assertEqual(routes, expected)

    def test_no_evaluation_or_recovery_post_routes(self):
        low = SERVER_SRC.lower()
        for token in ("/api/chaos/eval", "/api/eval", "/api/recovery",
                      "/api/chaos/recovery", "/api/receipt", "/api/snapshot"):
            self.assertNotIn(token, low, msg=token)

    def test_chaos_modules_have_no_provider_or_network_imports(self):
        imports = re.compile(r"^\s*(?:import|from)\s+(\S+)", re.M)
        for mod in ("chaos_simulation.py", "chaos_evaluation.py",
                    "chaos_recovery.py"):
            src = (ROOT / "backend" / mod).read_text()
            for name in imports.findall(src):
                top = name.split(".")[0]
                self.assertNotIn(top, ("meta_adapter", "urllib", "socket",
                                       "socketserver", "subprocess",
                                       "http", "ssl"),
                                 msg=f"{mod}:{name}")
            for token in ("os.system", "MODEL_API_KEY", "check_output",
                          "Popen"):
                self.assertNotIn(token, src, msg=f"{mod}:{token}")

    def test_fixtures_untouched_by_evaluation_and_recovery(self):
        import hashlib
        from backend.chaos_evaluation import evaluate
        from backend.chaos_recovery import run_recovery_test

        def digest():
            h = hashlib.sha256()
            for name in sorted((ROOT / "fixtures" / "chaos-lab").iterdir()):
                h.update(name.read_bytes())
            return h.hexdigest()
        before = digest()
        evaluate()
        run_recovery_test("CHS-ASSIGN-01", "restore-assignments")
        run_recovery_test("CHS-ACK-01", "reconcile-feed")
        self.assertEqual(digest(), before)


class ManifestConsistencyTest(unittest.TestCase):
    """Area H support: acceptance manifest must match observed state."""

    MANIFEST = ROOT / "tests" / "artifacts" / "mc-006-acceptance.json"

    def test_manifest_exists_with_required_sections(self):
        self.assertTrue(self.MANIFEST.exists(), msg=str(self.MANIFEST))
        manifest = json.loads(self.MANIFEST.read_text())
        for section in ("milestone", "acceptance_timestamp_utc",
                        "test_command", "test_totals", "acceptance_areas",
                        "source_artifacts", "security_boundaries",
                        "limitations", "overall_status"):
            self.assertIn(section, manifest, msg=section)
        self.assertEqual(set(manifest["acceptance_areas"]),
                         {"A", "B", "C", "D", "E", "F", "G", "H"})

    def test_manifest_artifact_hashes_match(self):
        import hashlib
        manifest = json.loads(self.MANIFEST.read_text())
        for rel, recorded in manifest["source_artifacts"].items():
            data = (ROOT / rel).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), recorded,
                             msg=rel)

    def test_manifest_metrics_match_production(self):
        from backend.chaos_evaluation import evaluate
        manifest = json.loads(self.MANIFEST.read_text())
        self.assertEqual(manifest["evaluation_metrics"]["confusion"],
                         evaluate()["confusion"])


if __name__ == "__main__":
    unittest.main()
