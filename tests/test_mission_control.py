"""Mission Control first slice: read-only wiring tests. No network, no live calls."""

import os
import re
import unittest
from pathlib import Path

from backend.server import handle_request, new_context

ROOT = Path(__file__).resolve().parents[1]


class ControlShellTest(unittest.TestCase):
    def test_pages_and_assets_load(self):
        cases = [("/control.html", "html"), ("/mission.css", "css"),
                 ("/control.css", "css"), ("/control.js", "javascript"),
                 ("/mission.html", "html")]
        for target, mime in cases:
            status, _, content_type = handle_request("GET", target, None, new_context())
            self.assertEqual(status, 200, msg=target)
            self.assertIn(mime, content_type, msg=target)

    def test_three_panels_and_two_views(self):
        html = (ROOT / "frontend" / "control.html").read_text()
        for element_id in ("view-overview", "view-investigation", "mcList",
                           "mcInspector", "mcHero", "mcSteps", "fieldLink",
                           "mcSummary", "mcFilters", "mcSearch"):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn('href="mission.html"', html)
        self.assertIn("fictional", html.lower())
        self.assertIn("never locks predictions", html)

    def test_group_filter_search_default_selection(self):
        html = (ROOT / "frontend" / "control.html").read_text()
        js = (ROOT / "frontend" / "control.js").read_text()
        css = (ROOT / "frontend" / "control.css").read_text()
        self.assertIn('class="field-link"', html)
        self.assertIn(".field-link", css)
        for token in ("data-filter", "aria-pressed", "group-h", "mcSearch",
                      "renderList(true)", "visibleItems",
                      "Policy quotations", "Deterministic calculations",
                      "Contradictions", "Hypotheses", "Open questions"):
            self.assertIn(token, js + html, msg=token)

    def test_loading_error_unavailable_states(self):
        js = (ROOT / "frontend" / "control.js").read_text()
        html = (ROOT / "frontend" / "control.html").read_text()
        for token in ("Loading backend evidence", "could not be reached",
                      "Unavailable", "No evidence matches this filter",
                      "Select an evidence item"):
            self.assertIn(token, js + html, msg=token)

    def test_no_live_calls_or_mutations(self):
        js = (ROOT / "frontend" / "control.js").read_text()
        # Forbid action patterns (methods, mutation routes, live modes), not
        # the words "reveal"/"approval", which the read-only lab must name
        # to explain that those actions happen elsewhere.
        for forbidden in ("mode=live", '"live"', "PUT", "DELETE",
                          "/predict", "/reveal", "/intervention", "/approval",
                          "prediction/lock"):
            self.assertNotIn(forbidden, js, msg=forbidden)
        self.assertEqual(js.count('method: "POST"'), 1)
        self.assertIn('"/api/chaos/run"', js)
        fetched = set(re.findall(r'fetch\("([^"]+)"', js))
        self.assertEqual(fetched, {"/api/mission", "/api/mission/proposal",
                           "/api/chaos/run"})
        self.assertIn("chaos-results/", js)
        self.assertEqual(js.count("fetch("), 7)

    def test_all_control_ids_and_routes_resolve(self):
        html = (ROOT / "frontend" / "control.html").read_text()
        js = (ROOT / "frontend" / "control.js").read_text()
        known_ids = set(re.findall(r'id="([^"]+)"', html + js))
        for element_id in set(re.findall(r'getElementById\("([^"]+)"\)', js)):
            self.assertIn(element_id, known_ids, msg=element_id)
        routes = set(re.findall(r'path == "([^"]+)"', (ROOT / "backend" / "server.py").read_text()))
        for url in set(re.findall(r'["\'](/api/[^"\']+)["\']', js)):
            self.assertIn(url.split("?")[0], routes, msg=url)


def _tmp_json(case, payload):
    import json
    import tempfile

    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(payload, tmp)
    tmp.close()
    case.addCleanup(os.unlink, tmp.name)
    return tmp.name


def exec_frontend(case, actions, mission, fail=False, proposal="NONE",
                  chaos_dir=None, chaos_run=None):
    import json
    import subprocess

    snap = _tmp_json(case, mission)
    acts = _tmp_json(case, actions)
    args = ["node", str(ROOT / "tests" / "mc_graph_harness.js"),
            str(ROOT / "frontend" / "control.js"), "FAIL" if fail else snap, acts]
    if proposal != "NONE":
        args.append(_tmp_json(case, proposal))
    if chaos_dir is not None:
        if proposal == "NONE":
            args.append("NONE")
        args.append(chaos_dir)
    if chaos_run is not None:
        if chaos_dir is None:
            if proposal == "NONE":
                args.append("NONE")
            args.append("frontend/chaos-results")
        args.append("NONE" if chaos_run == "FORBIDDEN"
                    else _tmp_json(case, chaos_run))
    proc = subprocess.run(args, capture_output=True, text=True, timeout=60)
    case.assertEqual(proc.returncode, 0, msg=proc.stderr[-2000:])
    return json.loads(proc.stdout)


def assert_no_withheld(case, out):
    for panel in ("inspector", "list", "graph", "illust", "lab", "labStatus",
                  "chaosList", "chaosDetail", "chaosFlow"):
        for token in ("SRC-FEED-GAP", "SRC-FEED", "09:40"):
            case.assertNotIn(token, out[panel], msg=panel)


class EvidenceGraphTest(unittest.TestCase):
    def test_edges_have_provenance_and_known_status(self):
        from backend.investigation import DOC_REFS

        js = (ROOT / "frontend" / "control.js").read_text()
        status, mission, _ = handle_request("GET", "/api/mission", None, new_context())
        self.assertEqual(status, 200)
        allowed = set(DOC_REFS)
        for cases in mission["evidence"]["categories"].values():
            allowed.update(cases)
        nodes = set(re.findall(r'\{id: "(\w+)"', js.split("const EDGES")[0]))
        edge_blocks = re.findall(r"\{s: \"(\w+)\", t: \"(\w+)\"[^}]*?type: \"([\w-]+)\"[^}]*?status: \"(\w+)\"[^}]*?refs: \[([^\]]*)\]",
                                 js.split("const ILLUST_STEPS")[0])
        self.assertTrue(edge_blocks)
        for source, target, kind, status, refs in edge_blocks:
            self.assertIn(source, nodes, msg=source)
            self.assertIn(target, nodes, msg=target)
            self.assertIn(kind, ("conflicts-with", "measured-against",
                                 "computed-from", "asserts", "relevant-to"), msg=kind)
            self.assertIn(status, ("verified", "reported", "hypothesized"))
            for ref in re.findall(r'"([^"]+)"', refs):
                self.assertIn(ref, allowed, msg=ref)

    def test_no_causal_arrows_or_withheld_content(self):
        js = (ROOT / "frontend" / "control.js").read_text()
        html = (ROOT / "frontend" / "control.html").read_text()
        css = (ROOT / "frontend" / "control.css").read_text()
        for token in ("SRC-FEED-GAP", "09:40", "SRC-FEED", "ack-found", "no-ack"):
            self.assertNotIn(token, js + html)
        self.assertNotIn('"causes"', js)
        self.assertNotIn('type: "supports"', js)
        for marker in ("marker-end", "marker-start"):
            self.assertNotIn(marker, js + html + css)
        self.assertIn("relevance is not causation", js + html)
        self.assertIn("does not independently prove an acknowledgment was lost", js)
        self.assertIn("disagreement itself", js)

    def test_node_layout_and_responsive_presentation(self):
        import re

        js = (ROOT / "frontend" / "control.js").read_text()
        html = (ROOT / "frontend" / "control.html").read_text()
        css = (ROOT / "frontend" / "control.css").read_text()
        nodes = re.findall(r'\{id: "(\w+)", label: "([^"]+)", x: (\d+), y: (\d+)', js)
        self.assertEqual(len(nodes), 7)
        boxes = [(nid, int(x) - 62, int(y) - 20, int(x) + 62, int(y) + 20)
                 for nid, _, x, y in nodes]
        for i, (a, ax0, ay0, ax1, ay1) in enumerate(boxes):
            for b, bx0, by0, bx1, by1 in boxes[i + 1:]:
                overlap = ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1
                self.assertFalse(overlap, msg=f"{a} overlaps {b}")
        self.assertIn('viewBox="0 0 660 420"', html)
        self.assertIn("#mcGraph { width: 100%", css)
        self.assertIn("paint-order", css)
        self.assertIn("@media", css)
        self.assertIn("never drawn as relationships", html)

    def test_illustrative_diagram_fenced(self):
        js = (ROOT / "frontend" / "control.js").read_text()
        html = (ROOT / "frontend" / "control.html").read_text()
        for step in ("Dashboard", "Queue Worker", "Gateway", "Acknowledgment"):
            self.assertIn(step, js)
        self.assertIn("not verified system topology", html)
        for token in ('data-gtab="evidence"', 'data-gtab="illustrative"',
                      "tabindex", 'role="button"', "keydown", "Enter"):
            self.assertIn(token, js + html, msg=token)

    def test_graph_read_only(self):
        js = (ROOT / "frontend" / "control.js").read_text()
        fetched = set(re.findall(r'fetch\("([^"]+)"', js))
        self.assertEqual(fetched, {"/api/mission", "/api/mission/proposal",
                           "/api/chaos/run"})
        self.assertIn("chaos-results/", js)
        self.assertEqual(js.count("fetch("), 7)

    # ---- Behavioral tests: execute the real control.js in Node ----
    def run_frontend(self, actions, fail=False):
        status, mission, _ = handle_request("GET", "/api/mission", None, new_context())
        self.assertEqual(status, 200)
        return exec_frontend(self, actions, mission if not fail else None, fail=fail)

    def assert_no_withheld(self, out):
        assert_no_withheld(self, out)

    def test_graph_node_to_inspector_sync(self):
        out = self.run_frontend([{"click-node": "misses"}])
        self.assertIn("Confirmed deadline misses", out["inspector"])
        self.assertIn("deterministic computation", out["inspector"])
        self.assertEqual(out["nodeAttrs"].get("misses", {}).get("aria-current"), "true")
        self.assertEqual(out["listBtnAttrs"].get("metric-4", {}).get("aria-current"), "true")
        self.assert_no_withheld(out)

    def test_report_node_without_ledger_item(self):
        out = self.run_frontend([{"click-node": "dispatcher"}])
        self.assertIn("Dispatcher report", out["inspector"])
        self.assertIn("reported, not independently verified", out["inspector"])
        self.assertIn("conflicts-with", out["inspector"])
        self.assertIn("does not establish which statement is true", out["inspector"])
        self.assert_no_withheld(out)

    def test_ledger_to_graph_sync_and_keyboard(self):
        out = self.run_frontend([{"click-item": "exp-H-ACK"},
                                 {"keydown-node": {"node": "hqueue", "key": "Enter"}}])
        self.assertEqual(out["nodeAttrs"].get("hack", {}).get("aria-current"), "false")
        self.assertIn("H-QUEUE", out["inspector"])
        self.assertIn("unverified", out["inspector"])
        self.assert_no_withheld(out)

    def test_tabs_and_search_preserve_graph(self):
        import re

        out = self.run_frontend([{"tab": "illustrative"}, {"search": "queue"},
                                 {"tab": "evidence"}, {"filter": "Hypotheses"}])
        self.assertIn("Queue Worker", out["illust"])
        self.assertEqual(len(re.findall(r'data-node="', out["graph"])), 7)
        self.assertIn("H-QUEUE", out["list"])
        self.assertEqual(out["gtabEvidenceDisplay"], "")
        self.assert_no_withheld(out)

    def test_frontend_error_state(self):
        out = self.run_frontend([], fail=True)
        self.assertIn("could not be reached", out["error"])
        for panel in ("inspector", "list", "graph", "illust"):
            self.assertNotIn("SRC-FEED-GAP", out[panel], msg=panel)


class ChaosLabTest(unittest.TestCase):
    def fresh_mission(self):
        status, mission, _ = handle_request("GET", "/api/mission", None, new_context())
        self.assertEqual(status, 200)
        return mission

    def assert_no_withheld(self, out):
        assert_no_withheld(self, out)

    def test_navigation_present(self):
        html = (ROOT / "frontend" / "control.html").read_text()
        self.assertEqual(html.count('data-view="view-chaos"'), 2)
        self.assertIn('id="view-chaos"', html)

    def test_catalog_lists_five_synthetic_scenarios(self):
        out = exec_frontend(self, [], self.fresh_mission())
        for sid in ("CHS-ASSIGN-01", "CHS-ACK-01", "CHS-NOTIFY-01",
                    "CHS-WINDOW-01", "CHS-ORDER-01"):
            self.assertIn(sid, out["chaosList"])
        self.assertIn("Synthetic scenario", out["chaosList"])
        self.assertIn("No scenario executes here", out["chaosList"])
        self.assert_no_withheld(out)

    def test_selection_updates_preview(self):
        out = exec_frontend(self, [{"select-scn": "CHS-ACK-01"}],
                            self.fresh_mission())
        for token in ("Missing acknowledgment in event feed",
                      "Hypothesized failure", "Preconditions",
                      "Proposed test", "Expected observable signal",
                      "Falsification", "Safety boundaries", "Availability",
                      "Verification criterion", "Observed detection",
                      "Recovery not established"):
            self.assertIn(token, out["chaosDetail"])
        self.assertIn("Not executable here", out["chaosDetail"])
        self.assert_no_withheld(out)

    def test_absent_evidence_scenario_is_honest(self):
        out = exec_frontend(self, [{"select-scn": "CHS-NOTIFY-01"}],
                            self.fresh_mission())
        self.assertIn("absent from fixtures", out["chaosDetail"])
        self.assertIn("No fixture record", out["chaosDetail"])
        self.assert_no_withheld(out)

    def test_illustrative_flow_is_not_evidence_topology(self):
        html = (ROOT / "frontend" / "control.html").read_text()
        out = exec_frontend(self, [], self.fresh_mission())
        for step in ("Intake", "Assignment", "Notification", "Acknowledgment"):
            self.assertIn(step, out["chaosFlow"])
        for old in ("Queue Worker", "Gateway", "Dashboard"):
            self.assertNotIn(old, out["chaosFlow"])
        self.assertIn("not verified system topology", html)
        self.assert_no_withheld(out)

    def test_no_fabricated_results_or_recovery(self):
        html = (ROOT / "frontend" / "control.html").read_text()
        out = exec_frontend(self, [{"select-scn": "CHS-ASSIGN-01"}],
                            self.fresh_mission())
        self.assertIn("Not run", out["chaosDetail"] + html)
        self.assertIn("Recovery not established", out["chaosDetail"])
        self.assertIn("None — scenario not run", out["chaosDetail"])
        for token in ("passed", "✓", "All systems operational"):
            self.assertNotIn(token, out["chaosDetail"] + out["chaosList"])
        self.assert_no_withheld(out)

    def test_fixture_evidence_navigates_to_inspector(self):
        out = exec_frontend(self, [{"select-scn": "CHS-WINDOW-01"},
                                   {"click-chaos-item": "ques-0"}],
                            self.fresh_mission())
        self.assertIn('data-item="ques-0"', out["chaosDetail"])
        self.assertIn("case-005", out["inspector"])
        self.assert_no_withheld(out)

    def test_workspace_compatibility_and_buttons(self):
        css = (ROOT / "frontend" / "control.css").read_text()
        out = exec_frontend(self, [{"select-scn": "CHS-ORDER-01"},
                                   {"click-node": "misses"}],
                            self.fresh_mission())
        self.assertIn("<button data-scn=", out["chaosList"])
        self.assertIn("Confirmed deadline misses", out["inspector"])
        self.assertIn(".chaos-grid", css)
        self.assertIn("@media", css)
        self.assert_no_withheld(out)


class ChaosResultsTest(unittest.TestCase):
    ARTIFACTS = ("CHS-ASSIGN-01", "CHS-ACK-01", "CHS-WINDOW-01")

    def fresh_mission(self):
        status, mission, _ = handle_request("GET", "/api/mission", None, new_context())
        self.assertEqual(status, 200)
        return mission

    def assert_no_withheld(self, out):
        assert_no_withheld(self, out)
        for token in ("SRC-FEED-GAP", "SRC-FEED", "09:40"):
            self.assertNotIn(token, out["chaosResult"])

    def artifact(self, sid, variant):
        import json

        path = ROOT / "frontend" / "chaos-results" / f"{sid}.{variant}.json"
        return json.loads(path.read_text())

    def test_artifacts_validated_and_reproducible(self):
        import json

        from backend.chaos_simulation import (run_simulation,
                                              validate_simulation_result)

        for sid in self.ARTIFACTS:
            for variant in ("baseline", "injected"):
                stored = self.artifact(sid, variant)
                validate_simulation_result(stored)
                regen = run_simulation(sid, variant)
                self.assertEqual(
                    json.dumps(regen, indent=2, sort_keys=True),
                    json.dumps(stored, indent=2, sort_keys=True))

    def test_artifact_contents_have_no_hidden_data(self):
        import json

        for sid in self.ARTIFACTS:
            for variant in ("baseline", "injected"):
                path = ROOT / "frontend" / "chaos-results" / f"{sid}.{variant}.json"
                text = path.read_text()
                stored = json.loads(text)
                self.assertEqual(stored["classification"], "synthetic simulation")
                self.assertEqual(stored["recovery"], "not-tested")
                for token in ("SRC-FEED", "09:40", "MODEL_API_KEY", "case-001",
                              "mission-case-001", "receipt"):
                    self.assertNotIn(token, text, msg=f"{sid}.{variant}:{token}")

    def test_injected_viewer_shows_attribution(self):
        out = exec_frontend(self, [{"select-scn": "CHS-ASSIGN-01"},
                                   {"select-variant": "injected"}],
                            self.fresh_mission())
        result = out["chaosResult"]
        for token in ("previously generated result",
                      "Validated at artifact generation",
                      "Newly introduced findings", "CHS-A, CHS-B, CHS-C",
                      "Preexisting findings",
                      "Classification changes vs baseline",
                      "confirmed-miss", "not tested",
                      "not Field Mission evidence"):
            self.assertIn(token, result, msg=token)
        self.assertEqual(out["varPressed"].get("injected"), "true")
        self.assert_no_withheld(out)

    def test_baseline_viewer_and_window_classification(self):
        out = exec_frontend(self, [{"select-scn": "CHS-WINDOW-01"},
                                   {"select-variant": "baseline"}],
                            self.fresh_mission())
        self.assertIn("window-observability: CHS-W1", out["chaosResult"])
        self.assertIn("incomplete", out["chaosResult"])
        self.assertIn("CHS-W2</strong> — confirmed-miss", out["chaosResult"])
        self.assertNotIn("Newly introduced findings", out["chaosResult"])
        self.assert_no_withheld(out)

    def test_malformed_artifact_rejected(self):
        import tempfile

        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        Path(tmp, "CHS-ACK-01.injected.json").write_text('{"schema": "nope"}')
        out = exec_frontend(self, [{"select-scn": "CHS-ACK-01"},
                                   {"select-variant": "injected"}],
                            self.fresh_mission(), chaos_dir=tmp)
        self.assertIn("Artifact invalid — not displayed", out["chaosResult"])

    def test_missing_artifact_rejected(self):
        import tempfile

        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        out = exec_frontend(self, [{"select-scn": "CHS-ACK-01"},
                                   {"select-variant": "injected"}],
                            self.fresh_mission(), chaos_dir=tmp)
        self.assertIn("Artifact invalid — not displayed", out["chaosResult"])


class ChaosRunBrowserTest(unittest.TestCase):
    def fresh_mission(self):
        status, mission, _ = handle_request("GET", "/api/mission", None, new_context())
        self.assertEqual(status, 200)
        return mission

    def assert_no_withheld(self, out):
        assert_no_withheld(self, out)

    def run_payload(self):
        import json

        from backend.chaos_simulation import run_simulation

        return {"ran": True, "executed_at": 1700000000,
                "result": run_simulation("CHS-ACK-01", "injected")}

    def test_no_automatic_execution_on_load(self):
        out = exec_frontend(self, [{"select-scn": "CHS-ACK-01"}],
                            self.fresh_mission())
        posts = [f for f in out["fetchLog"] if f["method"] == "POST"]
        self.assertEqual(posts, [])
        self.assertIn("Run this scenario now", out["chaosDetail"])
        self.assertIn("No run yet", out["chaosDetail"])

    def test_explicit_run_renders_executed_result(self):
        import json

        out = exec_frontend(
            self, [{"select-scn": "CHS-ACK-01"},
                   {"select-variant": "injected"}, {"click-run": True}],
            self.fresh_mission(), chaos_run=self.run_payload())
        posts = [f for f in out["fetchLog"] if f["method"] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["url"], "/api/chaos/run")
        self.assertEqual(json.loads(posts[0]["body"]),
                         {"scenario_id": "CHS-ACK-01", "variant": "injected"})
        executed = out["chaosExecuted"]
        for token in ("Newly executed synthetic run",
                      "not a historical artifact", "CHS-A",
                      "feed-source-reconciliation", "not tested",
                      "1700000000"):
            self.assertIn(token, executed, msg=token)
        self.assert_no_withheld(out)

    def test_run_requires_variant_choice(self):
        out = exec_frontend(self, [{"select-scn": "CHS-ACK-01"},
                                   {"click-run": True}],
                            self.fresh_mission(), chaos_run=self.run_payload())
        self.assertIn("Choose Baseline or Injected first", out["chaosExecuted"])
        posts = [f for f in out["fetchLog"] if f["method"] == "POST"]
        self.assertEqual(posts, [])

    def test_rejected_run_displays_safely(self):
        out = exec_frontend(self, [{"select-scn": "CHS-ACK-01"},
                                   {"select-variant": "injected"},
                                   {"click-run": True}],
                            self.fresh_mission(), chaos_run="FORBIDDEN")
        self.assertIn("Run rejected (forbidden)", out["chaosExecuted"])
        self.assertIn("Nothing was executed", out["chaosExecuted"])
        self.assert_no_withheld(out)


class ChaosDashboardTest(unittest.TestCase):
    def fresh_mission(self):
        status, mission, _ = handle_request("GET", "/api/mission", None, new_context())
        self.assertEqual(status, 200)
        return mission

    def assert_no_withheld(self, out):
        assert_no_withheld(self, out)
        for panel in ("evalReport", "recoveryRecords", "resultSummary"):
            for token in ("SRC-FEED-GAP", "SRC-FEED", "09:40"):
                self.assertNotIn(token, out[panel], msg=panel)

    def test_artifact_files_validated_and_reproducible(self):
        import json

        from backend.chaos_evaluation import evaluate
        from backend.chaos_recovery import (run_recovery_test,
                                            validate_recovery_result)

        report = json.loads(
            (ROOT / "frontend" / "chaos-results" / "chaos-eval-report.json").read_text())
        self.assertEqual(report, evaluate())
        for sid, rid in (("CHS-ASSIGN-01", "restore-assignments"),
                         ("CHS-ACK-01", "reconcile-feed"),
                         ("CHS-WINDOW-01", "none-available")):
            stored = json.loads(
                (ROOT / "frontend" / "chaos-results" / f"{sid}.recovery.json").read_text())
            self.assertEqual(stored, run_recovery_test(sid, rid))
            validate_recovery_result(stored)

    def test_evaluation_tab_renders_metrics(self):
        out = exec_frontend(self, [{"chaos-tab": "evaluation"}],
                            self.fresh_mission())
        rep = out["evalReport"]
        for token in ("Offline synthetic evaluation",
                      "True positives", "False positives",
                      "True negatives", "False negatives",
                      "100.0% (2 of 2)", "0.0% (0 of 2)",
                      "2 of 2 correct", "C8-order-anomaly",
                      "C9-malformed-record", "does not establish production"):
            self.assertIn(token, rep, msg=token)
        self.assertEqual(out["ctabPressed"].get("evaluation"), "true")
        posts = [f for f in out["fetchLog"] if f["method"] == "POST"]
        self.assertEqual(posts, [])
        self.assert_no_withheld(out)

    def test_undefined_metric_displays_not_defined(self):
        import json
        import tempfile

        report = json.loads(
            (ROOT / "frontend" / "chaos-results" / "chaos-eval-report.json").read_text())
        report["metrics"]["precision"] = None
        report["metrics"]["precision_denominator"] = 0
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        Path(tmp, "chaos-eval-report.json").write_text(json.dumps(report))
        out = exec_frontend(self, [{"chaos-tab": "evaluation"}],
                            self.fresh_mission(), chaos_dir=tmp)
        self.assertIn("Not defined", out["evalReport"])

    def test_recovery_tab_renders_records(self):
        out = exec_frontend(self, [{"chaos-tab": "recovery"}],
                            self.fresh_mission())
        rec = out["recoveryRecords"]
        for token in ("CHS-ASSIGN-01 — restore-assignments",
                      "CHS-ACK-01 — reconcile-feed",
                      "CHS-WINDOW-01 — none-available",
                      "baseline_restored", "feed_matches_source",
                      "insufficient verified",
                      "never production recovery"):
            self.assertIn(token, rec, msg=token)
        self.assertEqual(rec.count(">verified<"), 2)
        self.assertIn(">not-tested<", rec)
        self.assert_no_withheld(out)

    def test_results_summary_tab(self):
        out = exec_frontend(self, [{"chaos-tab": "results"}],
                            self.fresh_mission())
        summary = out["resultSummary"]
        for sid in ("CHS-ASSIGN-01", "CHS-ACK-01", "CHS-WINDOW-01"):
            self.assertIn(sid, summary)
        self.assertIn("previously generated", summary.lower())
        self.assert_no_withheld(out)

    def test_malformed_dashboard_artifacts_rejected(self):
        import tempfile

        for name, content in (
                ("chaos-eval-report.json", '{"schema": "nope"}'),
                ("CHS-ASSIGN-01.recovery.json",
                 '{"schema": "ChaosRecoveryResultV1", "scenario_id": "CHS-ASSIGN-01",'
                 ' "repair_id": "restore-assignments", "status": "verified"}')):
            tmp = tempfile.mkdtemp()
            self.addCleanup(lambda d=tmp: __import__("shutil").rmtree(
                d, ignore_errors=True))
            Path(tmp, name).write_text(content)
            tab = ("evaluation" if "eval" in name else "recovery")
            out = exec_frontend(self, [{"chaos-tab": tab}],
                                self.fresh_mission(), chaos_dir=tmp)
            panel = out["evalReport"] + out["recoveryRecords"]
            self.assertIn("not displayed", panel, msg=name)

    def test_no_evaluation_or_recovery_endpoints(self):
        from backend.server import handle_request, new_context

        for method, target in (("GET", "/api/chaos/eval"),
                               ("POST", "/api/chaos/eval"),
                               ("GET", "/api/chaos/recovery"),
                               ("POST", "/api/chaos/recovery")):
            status, _, _ = handle_request(method, target, None,
                                          new_context())
            self.assertEqual(status, 404, msg=f"{method} {target}")


class ReceiptLinkageTest(unittest.TestCase):
    RECEIPTS = ("1902c485a31f4e45", "10d84a313fd44022")

    def test_stored_receipts_lack_mission_linkage(self):
        from backend.receipt import load_receipt, verify_receipt

        seen = set()
        for rid in self.RECEIPTS:
            receipt = load_receipt(rid)
            self.assertEqual(receipt["case_id"], "case-001")
            for key in receipt:
                lowered = key.lower()
                for banned in ("mission", "experiment", "predict", "assess"):
                    self.assertNotIn(banned, lowered, msg=key)
            self.assertEqual(receipt["adjudication_status"], "pending")
            findings = verify_receipt(rid)
            self.assertEqual(findings["checks"]["integrity"], "pass")
            seen.add(receipt["receipt_id"])
        self.assertEqual(len(seen), 2)

    def test_no_receipt_retrieval_endpoint(self):
        server = (ROOT / "backend" / "server.py").read_text()
        self.assertNotIn("/api/receipt", server)
        self.assertNotIn("evaluator-private", server)

    def test_no_frontend_receipt_retrieval(self):
        js = (ROOT / "frontend" / "control.js").read_text()
        html = (ROOT / "frontend" / "control.html").read_text()
        for token in ("evaluator-private", "receipt.json", "receipt_id",
                      "1902c485a31f4e45", "10d84a313fd44022"):
            self.assertNotIn(token, js + html, msg=token)
        fetched = set(re.findall(r'fetch\("([^"]+)"', js))
        self.assertEqual(fetched, {"/api/mission", "/api/mission/proposal",
                           "/api/chaos/run"})
        self.assertIn("chaos-results/", js)
        self.assertEqual(js.count("fetch("), 7)

    def test_receipt_section_states_linkage_gap(self):
        html = (ROOT / "frontend" / "control.html").read_text()
        for token in ("No verified receipt linkage for this Field Mission",
                      "no mission, experiment, prediction, or assessment identifier",
                      "sharing case-001 does not establish",
                      "no read-only receipt endpoint",
                      "receipt verification is unavailable through this interface",
                      "stored, integrity-checked, adjudicated, authorized, executed",
                      "not that its investigation was accurate",
                      "Pending adjudication stays pending",
                      "record the mission and prediction identifiers",
                      "scoped read-only endpoint",
                      'href="investigate.html"'):
            self.assertIn(token, html, msg=token)
        self.assertNotIn("integrity verified", html)


class HypothesisLabTest(unittest.TestCase):
    def fresh_mission(self):
        status, mission, _ = handle_request("GET", "/api/mission", None, new_context())
        self.assertEqual(status, 200)
        return mission

    def locked_mission(self):
        from backend.experiment import build_registry, lock_prediction
        from backend.mission import choose_diagnostic, mission_view

        ctx = new_context()
        choose_diagnostic(ctx, "feed-probe")
        lock_prediction(ctx["experiment"], {
            "hypothesis_id": "H-ACK",
            "expected_finding": "ack-found",
            "expected_observation": "Source log holds a case-003 ack missing from the feed.",
            "criteria": "ack-found supports H-ACK; no-ack supports H-QUEUE.",
            "refs": ["case-003", "events.csv"],
        }, build_registry(ROOT), 1700000000, origin="human-authored")
        return mission_view(ctx)

    def test_hypotheses_rendered_from_backend(self):
        mission = self.fresh_mission()
        out = exec_frontend(self, [], mission)
        for h in mission["experiment"]["definition"]["hypotheses"]:
            self.assertIn(h["id"], out["lab"])
            self.assertIn(h["text"], out["lab"])
        self.assertIn("Assigned within 1 hour", out["lab"])
        self.assertIn("Acknowledgment-feed probe", out["lab"])
        self.assertIn("case-005 and case-006", out["labQuestions"])
        self.assert_no_withheld(out)

    def assert_no_withheld(self, out):
        assert_no_withheld(self, out)

    def test_relationship_language_and_no_scores(self):
        import re

        out = exec_frontend(self, [], self.fresh_mission())
        for token in ("relevant-to (hypothesized)", "asserts (reported)",
                      "unverified interpretation",
                      "None recorded in the backend record"):
            self.assertIn(token, out["lab"])
        self.assertNotIn("supports a causal", out["lab"])
        for panel in ("lab", "labStatus", "inspector"):
            self.assertIsNone(
                re.search(r"%|\b(probability|likely|probable)\b|confidence[^<>]{0,40}\d",
                           out[panel], re.IGNORECASE),
                msg=panel)
        self.assert_no_withheld(out)

    def test_hypothesis_selects_inspector(self):
        out = exec_frontend(self, [{"select-hyp": "H-ACK"}], self.fresh_mission())
        self.assertIn("H-ACK", out["inspector"])
        self.assertIn("unverified", out["inspector"])
        self.assertEqual(out["nodeAttrs"].get("hack", {}).get("aria-current"), "true")
        self.assertEqual(out["listBtnAttrs"].get("exp-H-ACK", {}).get("aria-current"), "true")
        self.assert_no_withheld(out)

    def test_lab_evidence_cross_select(self):
        out = exec_frontend(self, [{"select-hyp": "H-QUEUE"},
                                   {"click-lab-item": "contra-0"}], self.fresh_mission())
        self.assertIn('data-item="contra-0"', out["lab"])
        self.assertIn("Assignment practice vs assignment claims", out["inspector"])
        self.assert_no_withheld(out)

    def test_fresh_diagnostic_status(self):
        out = exec_frontend(self, [], self.fresh_mission())
        for token in ("No diagnostic selected", "No prediction locked",
                      "Withheld", "Not assessed", "Read-only"):
            self.assertIn(token, out["labStatus"])
        self.assert_no_withheld(out)

    def test_locked_status_withholds_outcome(self):
        out = exec_frontend(self, [], self.locked_mission())
        self.assertIn("Locked human-authored prediction: H-ACK expects ack-found",
                      out["labStatus"])
        self.assertIn("Acknowledgment-feed probe", out["labStatus"])
        self.assertIn("Withheld", out["labStatus"])
        self.assertNotIn("Revealed finding", out["labStatus"])
        self.assert_no_withheld(out)

class DecisionRoomTest(unittest.TestCase):
    def fresh_mission(self):
        status, mission, _ = handle_request("GET", "/api/mission", None, new_context())
        self.assertEqual(status, 200)
        return mission

    def decided_mission(self):
        from backend.experiment import assess, build_registry, lock_prediction, reveal_outcome
        from backend.mission import (
            choose_diagnostic,
            decide_intervention,
            intervention_proposal,
            mission_view,
        )

        ctx = new_context()
        choose_diagnostic(ctx, "feed-probe")
        lock_prediction(ctx["experiment"], {
            "hypothesis_id": "H-ACK",
            "expected_finding": "ack-found",
            "expected_observation": "Source log holds a case-003 ack missing from the feed.",
            "criteria": "ack-found supports H-ACK; no-ack supports H-QUEUE.",
            "refs": ["case-003", "events.csv"],
        }, build_registry(ROOT), 1700000000, origin="human-authored")
        reveal_outcome(ctx["experiment"], 1700000001)
        assessment = assess(ctx["experiment"])
        proposal = intervention_proposal(ctx)
        decide_intervention(ctx, "approve",
                            "Feed reconciliation is the smallest reversible next step.",
                            proposal["proposal_id"], proposal["version"])
        return mission_view(ctx), proposal, assessment

    def assert_no_withheld(self, out):
        assert_no_withheld(self, out)

    def test_fresh_room_has_no_proposal(self):
        out = exec_frontend(self, [], self.fresh_mission())
        html = (ROOT / "frontend" / "control.html").read_text()
        self.assertIn("Decision Room", html)
        self.assertIn("case-001", out["roomContext"])
        self.assertIn("Evidence completeness", out["roomCards"])
        self.assertIn("7 deterministic calculations", out["roomCards"])
        self.assertIn("2 open questions", out["roomCards"])
        self.assertIn("Not established", out["roomCards"])
        self.assertIn("No decision recorded", out["roomCards"] + out["roomReview"])
        self.assertIn("No proposal exists yet", out["roomProposal"])
        self.assertIn("Unavailable until a proposal exists", out["roomVerify"])
        self.assertIn("Recommendation is not authorization", out["roomProposal"] + out["roomCards"]
                      + (ROOT / "frontend" / "control.html").read_text())
        self.assert_no_withheld(out)

    def test_decided_room_shows_backend_proposal(self):
        mission, proposal, assessment = self.decided_mission()
        out = exec_frontend(self, [], mission, proposal=proposal)
        self.assertIn(proposal["proposal_id"], out["roomProposal"])
        self.assertIn(proposal["version"], out["roomProposal"])
        self.assertIn(proposal["text"], out["roomProposal"])
        for risk in proposal["risks"]:
            self.assertIn(risk, out["roomProposal"])
        stops = proposal["stop_conditions"]
        for stop in stops if isinstance(stops, list) else [stops]:
            self.assertIn(stop, out["roomVerify"])
        self.assertIn(proposal["next_role"], out["roomVerify"])
        self.assertIn(f"Deterministic assessment: {assessment['result']}",
                      out["roomCards"])
        self.assertIn("single-case support, not an organization-wide root cause",
                      out["roomCards"])
        self.assertIn("approve recorded on", out["roomCards"])
        self.assertIn("executed: false", out["roomCards"] + out["roomReview"])
        self.assertIn("Feed reconciliation is the smallest reversible next step.",
                      out["roomReview"])
        self.assertNotIn("No proposal exists yet", out["roomProposal"])
        self.assertNotIn("No decision recorded", out["roomReview"])
        self.assert_no_withheld(out)

    def test_room_evidence_navigation(self):
        mission, proposal, _ = self.decided_mission()
        out = exec_frontend(self, [{"click-room-item": "contra-0"},
                                   {"click-room-goto": "view-hypothesis"}],
                            mission, proposal=proposal)
        self.assertIn('data-room="contra-0"', out["roomCards"])
        self.assertIn("Assignment practice vs assignment claims", out["inspector"])
        self.assertEqual(out["activeView"], "view-hypothesis")
        self.assertIn("Open the Field Mission", out["roomCards"] + out["roomReview"])

    def test_lab_links_and_keyboard_buttons(self):
        html = (ROOT / "frontend" / "control.html").read_text()
        out = exec_frontend(self, [], self.fresh_mission())
        self.assertIn('href="mission.html"', html)
        self.assertIn("Perform authorized actions in the Field Mission", html)
        self.assertIn("<button data-hyp=", out["lab"])
        self.assertIn('data-view="view-hypothesis"', html)
        self.assert_no_withheld(out)


if __name__ == "__main__":
    unittest.main()
