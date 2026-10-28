"""Task 009.4c: classified provider-failure diagnostics. Transports mocked."""

import io
import json
import socket
import ssl
import unittest
import urllib.error
from unittest import mock

from backend.meta_adapter import (MetaModelAdapter, ProviderError,
                                  ProviderFailure)
from backend.server import handle_request, new_context


def http_error(code):
    return urllib.error.HTTPError(
        "https://api.meta.ai/v1/responses", code, f"HTTP Error {code}",
        {}, io.BytesIO(b'{"error": {"message": "provider says no"}}'))


def attempt(side_effect):
    adapter = MetaModelAdapter(api_key="fictional-probe-key")
    with mock.patch("urllib.request.urlopen", side_effect=side_effect):
        try:
            adapter.request_text("hello")
        except ProviderFailure as exc:
            return exc.diagnostic
    raise AssertionError("expected ProviderFailure")


class ClassificationTest(unittest.TestCase):
    def test_http_statuses(self):
        expected = {400: ("invalid-request", "confirmed"),
                    401: ("authorization", "confirmed"),
                    403: ("authorization", "confirmed"),
                    429: ("rate-limited", "confirmed"),
                    500: ("provider-error", "confirmed"),
                    503: ("provider-error", "confirmed")}
        for code, (category, transmission) in expected.items():
            diagnostic = attempt(http_error(code))
            self.assertEqual(diagnostic["category"], category, msg=code)
            self.assertEqual(diagnostic["http_status"], code, msg=code)
            self.assertEqual(diagnostic["exception_class"], "HTTPError", msg=code)
            self.assertFalse(diagnostic["timeout_occurred"], msg=code)
            self.assertEqual(diagnostic["transmission"], transmission, msg=code)

    def test_dns_connection_tls_timeout(self):
        cases = [
            (urllib.error.URLError(socket.gaierror(8, "nodename nor servname")),
             "dns", "unknown"),
            (urllib.error.URLError(ConnectionRefusedError(61, "refused")),
             "connection", "unknown"),
            (urllib.error.URLError(ssl.SSLError("certificate verify failed")),
             "tls", "unknown"),
            (socket.timeout("timed out"), "timeout", "possible"),
            (urllib.error.URLError(TimeoutError("timed out")), "timeout", "possible"),
        ]
        for error, category, transmission in cases:
            diagnostic = attempt(error)
            self.assertEqual(diagnostic["category"], category, msg=repr(error))
            self.assertIsNone(diagnostic["http_status"], msg=repr(error))
            self.assertEqual(diagnostic["transmission"], transmission, msg=repr(error))
        self.assertTrue(attempt(socket.timeout("x"))["timeout_occurred"])

    def test_incomplete_status_classified(self):
        adapter = MetaModelAdapter(api_key="fictional-probe-key")
        payload = {"status": "incomplete", "output": []}
        with mock.patch("urllib.request.urlopen",
                        _respond(json.dumps(payload).encode())):
            try:
                adapter.request_text("hello")
            except ProviderFailure as exc:
                self.assertEqual(exc.diagnostic["category"], "provider-error")
                self.assertEqual(exc.diagnostic["transmission"], "confirmed")
            else:
                raise AssertionError("expected ProviderFailure")

    def test_malformed_response_unchanged(self):
        from backend.meta_adapter import MalformedResponseError

        adapter = MetaModelAdapter(api_key="fictional-probe-key")
        payload = {"status": "completed", "output": []}
        with mock.patch("urllib.request.urlopen",
                        _respond(json.dumps(payload).encode())):
            with self.assertRaises(MalformedResponseError):
                adapter.request_text("hello")


def _respond(data):
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return data
    def opener(request, timeout=None):
        return FakeResponse()
    return opener


class SanitizedRecordTest(unittest.TestCase):
    def post_live_with(self, error):
        ctx = new_context()
        with mock.patch.object(MetaModelAdapter, "request_structured",
                              side_effect=error):
            status, data, _ = handle_request(
                "POST", "/api/investigation", b'{"mode": "live"}', ctx)
        return status, data, ctx

    def test_record_format_and_redaction(self):
        diagnostic = {"category": "authorization", "http_status": 401,
                      "exception_class": "HTTPError", "timeout_occurred": False,
                      "transmission": "confirmed"}
        status, data, ctx = self.post_live_with(
            ProviderFailure("provider request failed", diagnostic))
        self.assertEqual(status, 502)
        record = data["diagnostics"]
        for key in ("correlation_id", "timestamp", "model", "max_output_tokens",
                    "usage_available", "category", "http_status",
                    "exception_class", "timeout_occurred", "transmission"):
            self.assertIn(key, record, msg=key)
        self.assertEqual((record["model"], record["max_output_tokens"]),
                         ("muse-spark-1.3", 2048))
        self.assertFalse(record["usage_available"])
        blob = json.dumps(data) + json.dumps(ctx["diagnostics"])
        self.assertNotIn("fictional-probe-key", blob)
        for secret in ("Bearer", "Authorization", "provider says no"):
            self.assertNotIn(secret, blob)
        self.assertIn("401", data["message"])
        self.assertIn(record["correlation_id"], data["message"])
        self.assertNotIn("never sent", data["message"].lower())

    def test_unknown_transmission_wording(self):
        diagnostic = {"category": "dns", "http_status": None,
                      "exception_class": "URLError", "timeout_occurred": False,
                      "transmission": "unknown"}
        _, data, _ = self.post_live_with(
            ProviderFailure("provider request failed", diagnostic))
        self.assertIn("not established whether the request reached", data["message"])
        self.assertNotIn("never sent", data["message"].lower())

    def test_legacy_provider_error_falls_back_safely(self):
        _, data, _ = self.post_live_with(ProviderError("boom"))
        self.assertEqual(data["diagnostics"]["category"], "provider-error")
        self.assertEqual(data["diagnostics"]["transmission"], "unknown")

    def test_record_preserved_in_diagnostics_log(self):
        diagnostic = {"category": "timeout", "http_status": None,
                      "exception_class": "TimeoutError", "timeout_occurred": True,
                      "transmission": "possible"}
        _, data, ctx = self.post_live_with(
            ProviderFailure("provider request failed", diagnostic))
        self.assertEqual(ctx["diagnostics"][-1]["correlation_id"],
                         data["diagnostics"]["correlation_id"])


if __name__ == "__main__":
    unittest.main()
