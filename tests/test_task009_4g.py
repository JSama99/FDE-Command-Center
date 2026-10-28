"""Task 009.4g: smoke-test sanitized diagnostics. Transports mocked; no live calls."""

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from backend.meta_adapter import MetaModelAdapter, ProviderError, ProviderFailure
from backend import smoke_test


def run_smoke(side_effect):
    with mock.patch.dict("os.environ", {"MODEL_API_KEY": "fictional-env-key"}):
        with mock.patch.object(MetaModelAdapter, "request_text",
                              side_effect=side_effect):
            with mock.patch("urllib.request.urlopen",
                            side_effect=AssertionError("network used")):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    code = smoke_test.main()
    return code, buf.getvalue()


def failure(category, **fields):
    diagnostic = {"category": category, "http_status": None,
                  "exception_class": "HTTPError", "timeout_occurred": False,
                  "transmission": "confirmed"}
    diagnostic.update(fields)
    return ProviderFailure("provider request failed", diagnostic)


class SmokeDiagnosticTest(unittest.TestCase):
    def test_401_displayed_as_authorization(self):
        code, out = run_smoke(failure("authorization", http_status=401))
        self.assertEqual(code, 3)
        self.assertIn("category=authorization", out)
        self.assertIn("http_status=401", out)

    def test_400_429_5xx_classified(self):
        cases = [("invalid-request", 400), ("rate-limited", 429),
                 ("provider-error", 500)]
        for category, status in cases:
            _, out = run_smoke(failure(category, http_status=status))
            self.assertIn(f"category={category}", out, msg=category)
            self.assertIn(f"http_status={status}", out, msg=category)

    def test_network_and_timeout_categories(self):
        _, out = run_smoke(failure("dns", exception_class="URLError",
                                   transmission="unknown"))
        self.assertIn("category=dns", out)
        self.assertIn("transmission=unknown", out)
        _, out = run_smoke(failure("timeout", exception_class="TimeoutError",
                                   timeout_occurred=True, transmission="possible"))
        self.assertIn("category=timeout", out)
        self.assertIn("timeout_occurred=True", out)

    def test_sensitive_text_never_printed(self):
        secret = ProviderFailure(
            "secret-key-material-fictional Bearer header dump",
            {"category": "connection", "http_status": None,
             "exception_class": "URLError", "timeout_occurred": False,
             "transmission": "unknown"})
        _, out = run_smoke(secret)
        for forbidden in ("secret-key-material", "Bearer", "fictional-env-key",
                          "provider request failed"):
            self.assertNotIn(forbidden, out)

    def test_generic_fallback_prints_class_only(self):
        _, out = run_smoke(ValueError("secret-payload-contents"))
        self.assertIn("unexpected failure (ValueError)", out)
        self.assertNotIn("secret-payload-contents", out)

    def test_legacy_provider_error_safe(self):
        _, out = run_smoke(ProviderError("boom"))
        self.assertIn("unclassified", out)


if __name__ == "__main__":
    unittest.main()
