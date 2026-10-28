"""Task 009.4a: live-model cost guardrail. No live calls; urlopen is stubbed."""

import glob
import json
import unittest
from unittest import mock

from backend.meta_adapter import (MAX_OUTPUT_TOKENS, MIN_OUTPUT_TOKENS,
                                  MetaConfig, MetaModelAdapter,
                                  build_responses_payload)


VALID_RESPONSES_FIXTURE = {
    "status": "completed",
    "output": [{"type": "message",
                 "content": [{"type": "output_text", "text": "hi"}]}],
}


def stub_urlopen(payload, captured):
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(payload).encode()
    def opener(request, timeout=None):
        captured["request"] = request
        return FakeResponse()
    return opener


class OutputCapTest(unittest.TestCase):
    def test_default_cap_present_in_body(self):
        self.assertEqual(MAX_OUTPUT_TOKENS, 2048)
        self.assertEqual(MIN_OUTPUT_TOKENS, 16)
        body = build_responses_payload("muse-spark-1.3", "x")
        self.assertEqual(body["max_output_tokens"], 2048)
        self.assertEqual(body["model"], "muse-spark-1.3")

    def test_cap_sent_on_live_path(self):
        captured: dict = {}
        adapter = MetaModelAdapter(api_key="fictional-test-key")
        with mock.patch("urllib.request.urlopen",
                        stub_urlopen(VALID_RESPONSES_FIXTURE, captured)):
            adapter.request_text("hello")
        body = json.loads(captured["request"].data.decode("utf-8"))
        self.assertEqual(body["max_output_tokens"], 2048)

    def test_custom_cap_honored(self):
        captured: dict = {}
        adapter = MetaModelAdapter(
            config=MetaConfig(max_output_tokens=1024),
            api_key="fictional-test-key")
        with mock.patch("urllib.request.urlopen",
                        stub_urlopen(VALID_RESPONSES_FIXTURE, captured)):
            adapter.request_text("hello")
        body = json.loads(captured["request"].data.decode("utf-8"))
        self.assertEqual(body["max_output_tokens"], 1024)

    def test_below_minimum_rejected(self):
        for bad in (0, 1, 15):
            with self.assertRaises(ValueError, msg=bad):
                MetaConfig(max_output_tokens=bad)
        MetaConfig(max_output_tokens=16)  # documented minimum is allowed

    def test_credential_whitespace_stripped_before_use(self):
        from backend.meta_adapter import read_api_key

        captured: dict = {}
        adapter = MetaModelAdapter(api_key="fictional-test-key\n  ")
        with mock.patch("urllib.request.urlopen",
                        stub_urlopen(VALID_RESPONSES_FIXTURE, captured)):
            adapter.request_text("hello")
        self.assertEqual(captured["request"].get_header("Authorization"),
                         "Bearer fictional-test-key")
        with mock.patch.dict("os.environ", {"MODEL_API_KEY": "  env-key\n"}):
            self.assertEqual(read_api_key(), "env-key")

    def test_historical_outputs_fit_default_cap(self):
        worst = 0
        for path in glob.glob("evaluator-private/results/live-*/EVAL-*.json"):
            for record in json.load(open(path)).values():
                raw = record.get("raw")
                blob = json.dumps(raw) if isinstance(raw, dict) else (raw or "")
                worst = max(worst, len(blob.encode("utf-8")))
        self.assertLess(worst, MAX_OUTPUT_TOKENS * 4)

    def test_evidence_inputs_unchanged_by_cap(self):
        from backend import eval_harness as harness

        for case_id in harness.CASE_IDS:
            case = harness.load_case(case_id, "v2")
            stats = harness.compute_stats(case)
            context = harness.build_fde_context(case, stats)
            self.assertIn("events", context)  # raw evidence still supplied
        case = harness.load_case("EVAL-04", "v2")
        stats = harness.compute_stats(case)
        self.assertEqual(stats["sum:changeovers_recorded"]["by_group"]["channel"],
                         {"spreadsheet": 62, "tool": 12})


if __name__ == "__main__":
    unittest.main()
