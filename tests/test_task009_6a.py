"""Task 009.6a: provider response-status diagnostics. Offline only."""

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from backend.meta_adapter import (MetaModelAdapter, ProviderFailure,
                                  extract_response_text)


def text_response():
    return {"status": "completed", "output": [
        {"type": "message",
         "content": [{"type": "output_text", "text": "hi"}]}]}


class ResponseStatusTest(unittest.TestCase):
    def test_completed_returns_text(self):
        self.assertEqual(extract_response_text(text_response()), "hi")

    def test_missing_status_defaults_completed(self):
        response = text_response()
        del response["status"]
        self.assertEqual(extract_response_text(response), "hi")

    def test_incomplete_with_cap_reason(self):
        response = {"status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "output": []}
        try:
            extract_response_text(response)
        except ProviderFailure as exc:
            self.assertEqual(exc.diagnostic["response_status"], "incomplete")
            self.assertEqual(exc.diagnostic["incomplete_reason"], "max_output_tokens")
            self.assertEqual(exc.diagnostic["category"], "provider-error")
            self.assertEqual(exc.diagnostic["transmission"], "confirmed")
        else:
            raise AssertionError("expected ProviderFailure")

    def test_incomplete_with_filter_reason(self):
        response = {"status": "incomplete",
                    "incomplete_details": {"reason": "content_filter"},
                    "output": []}
        try:
            extract_response_text(response)
        except ProviderFailure as exc:
            self.assertEqual(exc.diagnostic["incomplete_reason"], "content_filter")
        else:
            raise AssertionError("expected ProviderFailure")

    def test_unknown_reason_dropped_not_logged(self):
        response = {"status": "incomplete",
                    "incomplete_details": {"reason": "some-weird-provider-text"},
                    "output": []}
        try:
            extract_response_text(response)
        except ProviderFailure as exc:
            self.assertEqual(exc.diagnostic["response_status"], "incomplete")
            self.assertIsNone(exc.diagnostic["incomplete_reason"])
            self.assertNotIn("some-weird-provider-text", json.dumps(exc.diagnostic))
        else:
            raise AssertionError("expected ProviderFailure")

    def test_failed_status(self):
        try:
            extract_response_text({"status": "failed", "output": []})
        except ProviderFailure as exc:
            self.assertEqual(exc.diagnostic["response_status"], "failed")
            self.assertIsNone(exc.diagnostic["incomplete_reason"])
        else:
            raise AssertionError("expected ProviderFailure")

    def test_unknown_status_maps_to_other(self):
        try:
            extract_response_text({"status": "mystery", "output": []})
        except ProviderFailure as exc:
            self.assertEqual(exc.diagnostic["response_status"], "other")
        else:
            raise AssertionError("expected ProviderFailure")

    def test_malformed_details_handled(self):
        for details in (None, [], "max_output_tokens", {"reason": 42}):
            response = {"status": "incomplete", "incomplete_details": details,
                        "output": []}
            try:
                extract_response_text(response)
            except ProviderFailure as exc:
                self.assertIsNone(exc.diagnostic["incomplete_reason"])
            else:
                raise AssertionError("expected ProviderFailure")

    def test_transport_diagnostics_carry_empty_status_fields(self):
        import urllib.error

        adapter = MetaModelAdapter(api_key="fictional-test-key")
        error = urllib.error.URLError("refused")
        with mock.patch("urllib.request.urlopen", side_effect=error):
            try:
                adapter.request_text("hello")
            except ProviderFailure as exc:
                self.assertIsNone(exc.diagnostic["response_status"])
                self.assertIsNone(exc.diagnostic["incomplete_reason"])
            else:
                raise AssertionError("expected ProviderFailure")


class StatusDisplayTest(unittest.TestCase):
    def test_smoke_shows_status_fields(self):
        from backend import smoke_test

        diagnostic = {"category": "provider-error", "http_status": None,
                      "exception_class": "ProviderError",
                      "timeout_occurred": False, "transmission": "confirmed",
                      "response_status": "incomplete",
                      "incomplete_reason": "max_output_tokens"}
        with mock.patch.dict("os.environ", {"MODEL_API_KEY": "fictional-env-key"}):
            with mock.patch.object(
                    MetaModelAdapter, "request_text",
                    side_effect=ProviderFailure("x", diagnostic)):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    code = smoke_test.main()
        self.assertEqual(code, 3)
        self.assertIn("response_status=incomplete", buf.getvalue())
        self.assertIn("incomplete_reason=max_output_tokens", buf.getvalue())

    def test_server_message_names_status(self):
        from backend.server import handle_request, new_context

        diagnostic = {"category": "provider-error", "http_status": None,
                      "exception_class": "ProviderError",
                      "timeout_occurred": False, "transmission": "confirmed",
                      "response_status": "incomplete",
                      "incomplete_reason": "max_output_tokens"}
        with mock.patch.object(MetaModelAdapter, "request_structured",
                              side_effect=ProviderFailure("x", diagnostic)):
            status, data, _ = handle_request(
                "POST", "/api/investigation", b'{"mode": "live"}', new_context())
        self.assertEqual(status, 502)
        self.assertIn("Provider response status: incomplete", data["message"])
        self.assertIn("Incomplete reason: max_output_tokens", data["message"])
        self.assertEqual(data["diagnostics"]["response_status"], "incomplete")

    def test_safeguards_unchanged(self):
        from backend.meta_adapter import MAX_OUTPUT_TOKENS, MODEL_ID, MetaConfig

        config = MetaConfig()
        self.assertEqual((config.model, config.max_output_tokens,
                          config.timeout_seconds),
                         (MODEL_ID, MAX_OUTPUT_TOKENS, 30))


if __name__ == "__main__":
    unittest.main()
