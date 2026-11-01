"""Task 009.7f: historical receipt compatibility. Offline only.

The known receipt 1902c485a31f4e45 is NEVER modified by these tests: all
mutation scenarios run on private temp copies.
"""

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.receipt import (ReceiptError, load_receipt, record_adjudication,
                             review_text, verify_receipt, write_receipt)

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_ID = "1902c485a31f4e45"
HISTORICAL_DIR = ROOT / "evaluator-private" / "receipts" / HISTORICAL_ID


def snapshot(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(directory).iterdir()) if p.is_file()}


def temp_copy(test):
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    dst = Path(tmp) / "receipts" / HISTORICAL_ID
    shutil.copytree(HISTORICAL_DIR, dst)
    return Path(tmp) / "receipts"


class HistoricalReceiptTest(unittest.TestCase):
    def test_receipt_present_and_readable(self):
        self.assertTrue((HISTORICAL_DIR / "receipt.json").is_file())
        receipt = load_receipt(HISTORICAL_ID)
        self.assertEqual(receipt["receipt_id"], HISTORICAL_ID)
        self.assertEqual(receipt["validation"]["result"], "accepted")

    def test_stored_hash_matches_content(self):
        receipt = load_receipt(HISTORICAL_ID)
        findings = verify_receipt(HISTORICAL_ID)
        self.assertEqual(findings["checks"]["integrity"], "pass")
        self.assertEqual(receipt["adjudication_status"], "pending")

    def test_evidence_manifest_verifiable(self):
        findings = verify_receipt(HISTORICAL_ID)
        self.assertEqual(findings["checks"]["evidence"], "pass")

    def test_validator_provenance_preserved(self):
        receipt = load_receipt(HISTORICAL_ID)
        self.assertTrue(receipt["validation"]["validator_code_sha256"])
        findings = verify_receipt(HISTORICAL_ID)
        self.assertEqual(findings["checks"]["validator_code"], "changed-since-issue")

    def test_drift_reported_not_invalid(self):
        findings = verify_receipt(HISTORICAL_ID)
        self.assertEqual(findings["checks"]["schema-status"],
                         "validator-version-drift")
        self.assertNotEqual(findings["checks"]["schema-status"],
                            "invalid-under-issued-rules")

    def test_inspection_leaves_bytes_untouched(self):
        before = snapshot(HISTORICAL_DIR)
        verify_receipt(HISTORICAL_ID)
        review_text(HISTORICAL_ID)
        self.assertEqual(snapshot(HISTORICAL_DIR), before)

    def test_existing_adjudication_preserved(self):
        before = snapshot(HISTORICAL_DIR)
        adjudication = json.loads((HISTORICAL_DIR / "adjudication.json").read_text())
        self.assertIn("decision", adjudication)
        with self.assertRaises(ReceiptError):
            record_adjudication(HISTORICAL_ID, "accept", "second look", "eng")
        self.assertEqual(snapshot(HISTORICAL_DIR), before)

    def test_tampered_copy_rejected(self):
        rdir = temp_copy(self)
        path = rdir / HISTORICAL_ID / "receipt.json"
        stored = json.loads(path.read_text())
        stored["investigation"]["unresolved_questions"] = ["rewritten"]
        path.write_text(json.dumps(stored))
        findings = verify_receipt(HISTORICAL_ID, receipts_dir=rdir)
        self.assertEqual(findings["checks"]["integrity"], "fail")

    def test_new_receipts_require_current_contract(self):
        historical = load_receipt(HISTORICAL_ID)["investigation"]
        with self.assertRaises(ValueError):
            write_receipt(historical, "low",
                          receipts_dir=Path(tempfile.mkdtemp()))
        # A current-schema investigation is still issuable.
        from tests.test_task004 import valid_payload

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        record = write_receipt(valid_payload(), "low",
                               receipts_dir=Path(tmp) / "r")
        findings = verify_receipt(record["receipt_id"],
                                  receipts_dir=Path(tmp) / "r")
        self.assertEqual(findings["checks"]["schema-status"], "current")

    def test_no_network_during_historical_review(self):
        before = snapshot(HISTORICAL_DIR)
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network used")):
            verify_receipt(HISTORICAL_ID)
            review_text(HISTORICAL_ID)
        self.assertEqual(snapshot(HISTORICAL_DIR), before)


if __name__ == "__main__":
    unittest.main()
