"""Task 004.1 tests: official Responses API compatibility. Stdlib unittest only.

Fixtures mirror the documented shape: POST /v1/responses with
{"model", "input"}, assistant text inside output message content blocks.
"""

import io
import json
import os
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from backend.investigation import produce_investigation
from backend.meta_adapter import (
    CREDENTIAL_ENV_VAR,
    DEFAULT_ENDPOINT,
    LEGACY_CREDENTIAL_ENV_VAR,
    MODEL_ID,
    MalformedResponseError,
    MetaConfig,
    MetaModelAdapter,
    MissingCredentialsError,
    ProviderError,
    extract_response_text,
)
from backend.smoke_test import main as smoke_main

ROOT = Path(__file__).resolve().parents[1]


def responses_fixture(inner_text: str, status: str = "completed") -> dict:
    return {
        "id": "resp_fictional_001",
        "object": "response",
        "created_at": 1790000000,
        "status": status,
        "model": MODEL_ID,
        "output": [
            {
                "type": "message",
                "id": "msg_fictional_1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": inner_text}],
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


class FakeHTTPResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def stub_urlopen(payload: dict, captured: dict):
    def fake(request, timeout=None):
        captured["request"] = request
        return FakeHTTPResponse(json.dumps(payload).encode("utf-8"))

    return fake


class OfficialApiFormatTest(unittest.TestCase):
    def test_correct_endpoint_and_request_format(self):
        captured: dict = {}
        adapter = MetaModelAdapter(api_key="fictional-test-key")
        with mock.patch(
            "urllib.request.urlopen",
            stub_urlopen(responses_fixture(json.dumps({"ok": True})), captured),
        ):
            self.assertEqual(adapter.request_structured({"prompt": "x"}), {"ok": True})
        request = captured["request"]
        self.assertEqual(request.full_url, DEFAULT_ENDPOINT)
        self.assertEqual(request.full_url, "https://api.meta.ai/v1/responses")
        self.assertEqual(request.get_method(), "POST")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], "muse-spark-1.3")
        self.assertIsInstance(body["input"], str)
        self.assertNotIn("mode", body)
        self.assertEqual(request.get_header("Authorization"), "Bearer fictional-test-key")

    def test_response_text_extraction(self):
        fixture = responses_fixture("first")
        fixture["output"][0]["content"].append({"type": "output_text", "text": "second"})
        self.assertEqual(extract_response_text(fixture), "firstsecond")

    def test_non_completed_status_rejected(self):
        with self.assertRaises(ProviderError):
            extract_response_text(responses_fixture("x", status="incomplete"))
        with self.assertRaises(ProviderError):
            extract_response_text(responses_fixture("x", status="failed"))

    def test_empty_output_rejected(self):
        with self.assertRaises(MalformedResponseError):
            extract_response_text({"status": "completed", "output": []})
        with self.assertRaises(MalformedResponseError):
            extract_response_text({"status": "completed", "output": [{"type": "reasoning"}]})

    def test_contributor_model_ids_rejected(self):
        with self.assertRaises(ValueError):
            MetaConfig(model="muse-spark-1.3-contributor")

    def test_model_api_key_is_primary(self):
        captured: dict = {}
        env = {CREDENTIAL_ENV_VAR: "primary-key", LEGACY_CREDENTIAL_ENV_VAR: "legacy-key"}
        with mock.patch.dict(os.environ, env, clear=False):
            adapter = MetaModelAdapter()
            with mock.patch(
                "urllib.request.urlopen",
                stub_urlopen(responses_fixture(json.dumps({"ok": True})), captured),
            ):
                adapter.request_structured({"prompt": "x"})
        self.assertEqual(captured["request"].get_header("Authorization"), "Bearer primary-key")

    def test_legacy_key_falls_back(self):
        captured: dict = {}
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(CREDENTIAL_ENV_VAR, None)
            os.environ[LEGACY_CREDENTIAL_ENV_VAR] = "legacy-key"
            try:
                adapter = MetaModelAdapter()
                with mock.patch(
                    "urllib.request.urlopen",
                    stub_urlopen(responses_fixture(json.dumps({"ok": True})), captured),
                ):
                    adapter.request_structured({"prompt": "x"})
            finally:
                os.environ.pop(LEGACY_CREDENTIAL_ENV_VAR, None)
        self.assertEqual(captured["request"].get_header("Authorization"), "Bearer legacy-key")


class OfficialEndToEndTest(unittest.TestCase):
    def test_live_shaped_response_validates(self):
        from tests.test_task004 import valid_payload

        inner = json.dumps(valid_payload())
        captured: dict = {}
        adapter = MetaModelAdapter(api_key="fictional-test-key")
        # Drive the full pipeline through the stubbed official transport.
        with mock.patch(
            "urllib.request.urlopen", stub_urlopen(responses_fixture(inner), captured)
        ):
            result = produce_investigation(adapter, ROOT)
        self.assertEqual(result["case_id"], "case-001")


class SmokeTestCommandTest(unittest.TestCase):
    def test_disabled_without_credentials(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(CREDENTIAL_ENV_VAR, None)
            os.environ.pop(LEGACY_CREDENTIAL_ENV_VAR, None)
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = smoke_main()
        self.assertEqual(code, 2)
        self.assertIn("disabled", buf.getvalue())

    def test_never_prints_key(self):
        with mock.patch.dict(os.environ, {CREDENTIAL_ENV_VAR: "super-secret-key"}, clear=False):
            buf = io.StringIO()
            with mock.patch(
                "urllib.request.urlopen", side_effect=urllib.error.URLError("down")
            ):
                with redirect_stdout(buf):
                    code = smoke_main()
        self.assertEqual(code, 3)
        self.assertNotIn("super-secret-key", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
