"""Task 009.6e: controlled reasoning budget. Transports mocked; no live calls."""

import io
import json
import unittest
from unittest import mock

from backend.meta_adapter import (INVESTIGATION_REASONING_EFFORT,
                                  MetaModelAdapter, MockAdapter,
                                  build_responses_payload)
from tests.test_task004 import valid_payload

VALID_TEXT = json.dumps(valid_payload())
VALID_RESPONSE = {
    "status": "completed",
    "output": [{"type": "message",
                "content": [{"type": "output_text", "text": VALID_TEXT}]}],
}


def capture(body_holder):
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(VALID_RESPONSE).encode()
    def opener(request, timeout=None):
        body_holder["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()
    return opener


class ReasoningEffortTest(unittest.TestCase):
    def test_default_body_unchanged(self):
        body = build_responses_payload("muse-spark-1.3", "x")
        self.assertNotIn("reasoning", body)
        self.assertEqual(body["max_output_tokens"], 4096)

    def test_low_effort_shape(self):
        body = build_responses_payload("muse-spark-1.3", "x",
                                       reasoning_effort="low")
        self.assertEqual(body["reasoning"], {"effort": "low"})

    def test_unknown_effort_rejected(self):
        for bad in ("none", "ultra", "", "LOW"):
            with self.assertRaises(ValueError, msg=bad):
                build_responses_payload("muse-spark-1.3", "x",
                                        reasoning_effort=bad)

    def test_text_path_sends_no_reasoning(self):
        held: dict = {}
        adapter = MetaModelAdapter(api_key="fictional-test-key")
        with mock.patch("urllib.request.urlopen", capture(held)):
            adapter.request_text("hello")
        self.assertNotIn("reasoning", held["body"])

    def test_structured_default_sends_no_reasoning(self):
        held: dict = {}
        adapter = MetaModelAdapter(api_key="fictional-test-key")
        with mock.patch("urllib.request.urlopen", capture(held)):
            adapter.request_structured({"evidence": True}, "Do it.")
        self.assertNotIn("reasoning", held["body"])

    def test_investigation_sends_low_and_validates(self):
        from backend.investigation import produce_investigation

        held: dict = {}
        adapter = MetaModelAdapter(api_key="fictional-test-key")
        with mock.patch("urllib.request.urlopen", capture(held)):
            result = produce_investigation(adapter, ".")
        self.assertEqual(held["body"]["reasoning"], {"effort": "low"})
        self.assertEqual(held["body"]["max_output_tokens"], 4096)
        self.assertEqual(held["body"]["model"], "muse-spark-1.3")
        # Existing validators ran unchanged: structured output accepted.
        self.assertEqual(result["case_id"], "case-001")
        self.assertTrue(result["investigation"]["observations"])

    def test_mock_records_effort(self):
        mock_adapter = MockAdapter()
        self.assertIsNone(mock_adapter.last_reasoning_effort)
        self.assertEqual(INVESTIGATION_REASONING_EFFORT, "low")


if __name__ == "__main__":
    unittest.main()
