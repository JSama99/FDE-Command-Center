"""Task 009.4: offline mission acceptance + live-call readiness. No live calls.

Every network-touching path is blocked: any real request attempt fails loudly.
"""

import json
import unittest
from pathlib import Path
from unittest import mock

from backend.server import handle_request, new_context
from tests.test_task009 import PREDICT, decide


def call(ctx, method, target, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    status, data, _ = handle_request(method, target, body, ctx)
    return status, data


def lock_reveal_assess(ctx, payload=PREDICT):
    assert call(ctx, "POST", "/api/experiment/predict", payload)[0] == 200
    assert call(ctx, "POST", "/api/experiment/reveal", {})[0] == 200
    assert call(ctx, "POST", "/api/experiment/assess", {})[0] == 200


class OfflineAcceptanceTest(unittest.TestCase):
    def test_01_assets_load(self):
        ctx = new_context()
        for target, mime in (("/mission.html", "html"),
                             ("/mission.css", "css"),
                             ("/mission.js", "javascript")):
            status, _, content_type = handle_request("GET", target, None, ctx)
            self.assertEqual(status, 200, msg=target)
            self.assertIn(mime, content_type, msg=target)

    def test_02_five_workspaces(self):
        html = (Path(__file__).resolve().parents[1] / "frontend" / "mission.html").read_bytes()
        for workspace in (b"ws-overview", b"ws-evidence", b"ws-diagnostics",
                          b"ws-decision", b"ws-report"):
            self.assertIn(workspace, html)

    def test_03_evidence_and_constraints(self):
        _, view = call(new_context(), "GET", "/api/mission")
        self.assertTrue(view["constraint"])
        self.assertTrue(all("quote" in q for q in view["constraint"]))
        labels = [c["label"] for c in view["evidence"]["calculations"]]
        self.assertIn("Assigned within 1 hour", labels)

    def test_04_to_07_feed_probe_conceal_reveal_assess(self):
        ctx = new_context()
        self.assertEqual(call(ctx, "POST", "/api/mission/diagnostic",
                              {"choice": "feed-probe"})[0], 200)
        _, result = call(ctx, "GET", "/api/mission/diagnostic/result")
        self.assertTrue(result["requires_prediction"])
        self.assertNotIn("SRC-FEED-GAP", json.dumps(result))
        lock_reveal_assess(ctx)
        self.assertEqual(ctx["experiment"]["status"], "assessed")
        self.assertIn("finding", ctx["experiment"]["outcome"])

    def test_08_proposal_follows_supported_outcome(self):
        ctx = new_context()
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        lock_reveal_assess(ctx)
        _, proposal = call(ctx, "GET", "/api/mission/proposal")
        self.assertEqual((proposal["proposal_id"], proposal["version"]), ("PROP-002", "v1"))

    def test_09_placeholder_rejected_then_10_11_approved_and_bound(self):
        ctx = new_context()
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        lock_reveal_assess(ctx)
        _, proposal = call(ctx, "GET", "/api/mission/proposal")
        bound = {"proposal_id": proposal["proposal_id"],
                 "proposal_version": proposal["version"]}
        self.assertEqual(call(ctx, "POST", "/api/mission/intervention",
                              {"decision": "approve", "note": "n/a", **bound})[0], 400)
        status, data = call(ctx, "POST", "/api/mission/intervention", {
            "decision": "approve",
            "note": "Reconciliation is bounded to supplied rows and read-only.",
            **bound})
        self.assertEqual(status, 200)
        record = ctx["mission"]["intervention"]
        self.assertEqual((record["proposal"]["proposal_id"],
                          record["proposal"]["version"]), ("PROP-002", "v1"))

    def test_12_thirteen_sections_13_not_executed(self):
        ctx = new_context()
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        lock_reveal_assess(ctx)
        decide(ctx, "approve", "Bounded and read-only.")
        _, report = call(ctx, "GET", "/api/mission/report")
        self.assertEqual(len(report["readable_sections"]), 13)
        confirm = next(s for s in report["sections"]
                       if s["title"] == "Production-action confirmation")
        self.assertFalse(confirm["body"]["executed"])

    def test_audit_path_proposes_prop003(self):
        ctx = new_context()
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "timestamp-audit"})
        _, result = call(ctx, "GET", "/api/mission/diagnostic/result")
        self.assertIn("5 of 7", result["finding"])
        _, proposal = call(ctx, "GET", "/api/mission/proposal")
        self.assertEqual((proposal["proposal_id"], proposal["version"]), ("PROP-003", "v1"))
        decide(ctx, "defer", "Coverage review needs the coordinator present.")
        _, report = call(ctx, "GET", "/api/mission/report")
        self.assertEqual(len(report["readable_sections"]), 13)


class LiveReadinessPreflightTest(unittest.TestCase):
    def test_model_endpoint_and_limits(self):
        from backend.meta_adapter import (BASE_URL, DEFAULT_ENDPOINT,
                                          MODEL_ID, MetaConfig)

        self.assertEqual(MODEL_ID, "muse-spark-1.3")
        self.assertEqual(DEFAULT_ENDPOINT, BASE_URL + "/responses")
        config = MetaConfig()
        self.assertEqual(config.mode, "standard")
        self.assertEqual(config.timeout_seconds, 30)
        with self.assertRaises(ValueError):
            MetaConfig(model="muse-spark-1.3-contributor")
        with self.assertRaises(ValueError):
            MetaConfig(mode="contributor")

    def test_missing_credentials_refuse_safely(self):
        from backend.meta_adapter import (MetaModelAdapter,
                                          MissingCredentialsError)

        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(MissingCredentialsError):
                MetaModelAdapter()._key()
            status, data = call(new_context(), "POST", "/api/investigation",
                                {"mode": "live"})
            self.assertEqual(status, 503)

    def test_single_attempt_no_retries_or_key_exposure(self):
        from backend.meta_adapter import MetaModelAdapter, ProviderError
        import urllib.error

        adapter = MetaModelAdapter(api_key="fictional-probe-key")
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("down")) as mocked:
            with self.assertRaises(ProviderError):
                adapter.request_text("hello")
            self.assertEqual(mocked.call_count, 1)
        request = mocked.call_args[0][0]
        self.assertEqual(request.full_url, "https://api.meta.ai/v1/responses")

    def test_key_never_in_frontend(self):
        root = Path(__file__).resolve().parents[1]
        for path in (root / "frontend").rglob("*"):
            if path.is_file() and path.suffix in (".js", ".html"):
                text = path.read_text()
                self.assertNotIn("MODEL_API_KEY", text, msg=str(path))
                self.assertNotIn("META_API_KEY", text, msg=str(path))
                self.assertNotIn("Bearer ", text, msg=str(path))

    def test_full_mission_with_network_blocked(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network used")):
            ctx = new_context()
            call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
            lock_reveal_assess(ctx)
            self.assertEqual(
                decide(ctx, "approve", "Offline acceptance walkthrough.")[0], 200)
            self.assertEqual(call(ctx, "GET", "/api/mission/report")[0], 200)


if __name__ == "__main__":
    unittest.main()
