"""Task 009.7c-P: receipt-enabled investigation path. Mocks only, no network."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.meta_adapter import MockAdapter
from backend.receipt import produce_investigation_with_receipt, verify_receipt
from tests.test_task004 import valid_payload


class CountingAdapter(MockAdapter):
    def __init__(self, canned):
        super().__init__(canned)
        self.invocations = 0

    def request_structured(self, context, instructions=None,
                           reasoning_effort=None):
        self.invocations += 1
        return super().request_structured(context, instructions,
                                          reasoning_effort)


def temp_dir(test):
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    return Path(tmp) / "receipts"


class ReceiptPathTest(unittest.TestCase):
    def test_validated_investigation_produces_one_receipt(self):
        adapter = CountingAdapter(valid_payload())
        rdir = temp_dir(self)
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network used")):
            outcome = produce_investigation_with_receipt(
                adapter, receipts_dir=rdir)
        self.assertEqual(adapter.invocations, 1)
        self.assertIsNotNone(outcome["receipt_id"])
        self.assertEqual(outcome["validation"], "accepted")
        self.assertTrue(outcome["storage"].endswith("receipt.json"))
        self.assertEqual(outcome["summary"]["case_id"], "case-001")
        findings = verify_receipt(outcome["receipt_id"], receipts_dir=rdir)
        self.assertEqual(findings["checks"]["integrity"], "pass")

    def test_invalid_investigation_produces_no_receipt(self):
        bad = valid_payload()
        bad["observations"] = [{"text": "x", "refs": ["nope"],
                                "basis": "computed"}]
        adapter = CountingAdapter(bad)
        rdir = temp_dir(self)
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network used")):
            with self.assertRaises(ValueError):
                produce_investigation_with_receipt(adapter, receipts_dir=rdir)
        self.assertEqual(adapter.invocations, 1)
        self.assertFalse(rdir.exists())

    def test_failed_write_never_reinvokes_model(self):
        adapter = CountingAdapter(valid_payload())
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network used")):
            with mock.patch("backend.receipt.write_receipt",
                            side_effect=RuntimeError("disk full")):
                outcome = produce_investigation_with_receipt(
                    adapter, receipts_dir=temp_dir(self))
        self.assertEqual(adapter.invocations, 1)
        self.assertIsNone(outcome["receipt_id"])
        self.assertIn("disk full", outcome["receipt_error"])
        self.assertTrue(outcome["investigation"]["observations"])

    def test_existing_api_behavior_unchanged(self):
        from backend.investigation import produce_investigation

        adapter = CountingAdapter(valid_payload())
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network used")):
            result = produce_investigation(adapter, ".")
        self.assertEqual(adapter.invocations, 1)
        self.assertNotIn("receipt_id", result)
        self.assertEqual(result["case_id"], "case-001")


if __name__ == "__main__":
    unittest.main()
