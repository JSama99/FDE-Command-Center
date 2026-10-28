"""Task 005 tests: AI Investigation Workspace server + UI smoke. Stdlib unittest only."""

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from backend.investigation import (
    EXPECTED_SECTIONS,
    build_evidence_registry,
    build_offline_investigation,
    validate_investigation,
)
from backend.report import build_case_report
from backend.server import handle_request, new_context

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "frontend" / "investigate.html"
JS_PATH = ROOT / "frontend" / "investigate.js"


def call(method: str, target: str, body: object = None, ctx: dict | None = None):
    ctx = ctx if ctx is not None else new_context(ROOT)
    raw = None if body is None else json.dumps(body).encode("utf-8")
    status, payload, _ctype = handle_request(method, target, raw, ctx)
    return status, payload, ctx


class OfflineInvestigationTest(unittest.TestCase):
    def test_offline_builder_validates(self):
        result = build_offline_investigation(ROOT)
        self.assertEqual(result["mode"], "offline-mock")
        inv = result["investigation"]
        for section in EXPECTED_SECTIONS:
            self.assertIn(section, inv)
        for hypo in inv["competing_hypotheses"]:
            self.assertEqual(hypo.get("status"), "hypothesis")


class ServerEndpointTest(unittest.TestCase):
    def test_report_endpoint(self):
        status, payload, _ = call("GET", "/api/report")
        self.assertEqual(status, 200)
        self.assertTrue(any("1 hour of creation" in q["quote"] for q in payload["policy_requirements"]))

    def test_mock_investigation_endpoint(self):
        status, payload, _ = call("GET", "/api/investigation?mode=mock")
        self.assertEqual(status, 200)
        self.assertEqual(payload["mode"], "offline-mock")
        registry = build_evidence_registry(build_case_report(ROOT))
        validate_investigation(payload["investigation"], registry)

    def test_live_requires_explicit_post(self):
        status, payload, _ = call("GET", "/api/investigation?mode=live")
        self.assertEqual(status, 400)

    def test_live_without_key_fails_safely(self):
        from backend.meta_adapter import CREDENTIAL_ENV_VAR, LEGACY_CREDENTIAL_ENV_VAR

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(CREDENTIAL_ENV_VAR, None)
            os.environ.pop(LEGACY_CREDENTIAL_ENV_VAR, None)
            status, payload, _ = call("POST", "/api/investigation", {"mode": "live"})
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "missing_credentials")

    def test_live_with_stubbed_provider(self):
        inner = json.dumps(build_offline_investigation(ROOT)["investigation"])
        envelope = {
            "id": "resp_fictional_002",
            "object": "response",
            "status": "completed",
            "model": "muse-spark-1.3",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": inner}],
                }
            ],
        }

        class FakeResponse:
            def read(self):
                return json.dumps(envelope).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "fictional-test-key"}, clear=False):
            with mock.patch("urllib.request.urlopen", return_value=FakeResponse()):
                status, payload, _ = call("POST", "/api/investigation", {"mode": "live"})
        self.assertEqual(status, 200)
        self.assertIn("investigation", payload)

    def test_approval_records_without_executing(self):
        status, payload, ctx = call("POST", "/api/approval", {"decision": "approve", "note": "ok"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["recorded"])
        self.assertFalse(payload["executed"])
        self.assertFalse(ctx["approvals"][0]["executed"])

    def test_approval_rejects_bad_decisions(self):
        status, _, _ = call("POST", "/api/approval", {"decision": "maybe"})
        self.assertEqual(status, 400)

    def test_no_production_execution_path(self):
        source = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
        for banned in ("os.system", "subprocess", "eval(", "exec("):
            self.assertNotIn(banned, source)


class UISmokeTest(unittest.TestCase):
    def test_page_wires_api_and_approval(self):
        html = HTML_PATH.read_text(encoding="utf-8")
        js = JS_PATH.read_text(encoding="utf-8")
        self.assertIn("/api/investigation?mode=mock", js)
        self.assertIn('"/api/investigation"', js)
        self.assertIn('"/api/approval"', js)
        self.assertIn("unverified interpretation", js)
        self.assertIn('id="approveBtn"', html)
        self.assertIn('id="rejectBtn"', html)

    def test_frontend_renders_safe_diagnostics(self):
        js = JS_PATH.read_text(encoding="utf-8")
        self.assertIn("data.diagnostics", js)
        self.assertIn("diag.correlation_id", js)

    def test_frontend_holds_no_secrets_or_hardcoded_findings(self):
        html = HTML_PATH.read_text(encoding="utf-8")
        js = JS_PATH.read_text(encoding="utf-8")
        for text in (html, js):
            self.assertNotIn("MODEL_API_KEY", text)
            self.assertNotIn("META_API_KEY", text)
            self.assertNotIn("Bearer", text)
            self.assertNotIn("case-001 met both", text)
            self.assertNotIn("3 of 7", text)


if __name__ == "__main__":
    unittest.main()
