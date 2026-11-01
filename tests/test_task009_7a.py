"""Task 009.7a: private receipts + offline adjudication. No network, no live calls."""

import json
import os
import shutil
import stat
import unittest
from pathlib import Path
from unittest import mock

from backend import receipt as receipts
from backend.receipt import (RECEIPTS_DIR, ReceiptError, load_receipt,
                             record_adjudication, review_text, verify_receipt,
                             write_receipt)
from backend.server import handle_request, new_context
from tests.test_task004 import valid_payload

ROOT = Path(__file__).resolve().parents[1]


def temp_case(tmp):
    base = Path(tmp) / "proj"
    shutil.copytree(ROOT / "fixtures", base / "fixtures")
    return base


class ReceiptIssueTest(unittest.TestCase):
    def test_invalid_investigation_refused(self):
        bad = valid_payload()
        bad["observations"] = [{"text": "x", "refs": ["nope"], "basis": "computed"}]
        with self.assertRaises(ValueError):
            write_receipt(bad, "low", receipts_dir=Path(self._tmp()) / "r")

    def _tmp(self):
        import tempfile

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        return tmp

    def test_roundtrip_and_reverify(self):
        tmp = self._tmp()
        record = write_receipt(valid_payload(), "low",
                               receipts_dir=Path(tmp) / "r")
        self.assertEqual(record["adjudication_status"], "pending")
        self.assertEqual(record["model_config"]["reasoning_effort"], "low")
        self.assertEqual(record["model_config"]["max_output_tokens"], 4096)
        self.assertIn("not provider-attested",
                      record["model_config"]["provenance"])
        findings = verify_receipt(record["receipt_id"],
                                  receipts_dir=Path(tmp) / "r")
        self.assertEqual(findings["checks"]["revalidation"], "pass")
        self.assertEqual(findings["checks"]["integrity"], "pass")
        self.assertEqual(findings["checks"]["evidence"], "pass")

    def test_restrictive_permissions(self):
        tmp = self._tmp()
        record = write_receipt(valid_payload(), None,
                               receipts_dir=Path(tmp) / "r")
        path = Path(tmp) / "r" / record["receipt_id"] / "receipt.json"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_receipt_tamper_detected(self):
        tmp = self._tmp()
        record = write_receipt(valid_payload(), "low",
                               receipts_dir=Path(tmp) / "r")
        path = Path(tmp) / "r" / record["receipt_id"] / "receipt.json"
        stored = json.loads(path.read_text())
        stored["investigation"]["observations"] = []
        path.write_text(json.dumps(stored))
        findings = verify_receipt(record["receipt_id"],
                                  receipts_dir=Path(tmp) / "r")
        self.assertEqual(findings["checks"]["integrity"], "fail")
        self.assertEqual(findings["checks"]["revalidation"], "pass")

    def test_evidence_tamper_detected(self):
        import tempfile

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        base = temp_case(tmp)
        rdir = Path(tmp) / "r"
        record = write_receipt(valid_payload(), "low", base_dir=base,
                               receipts_dir=rdir)
        (base / "fixtures" / "case-001" / "events.csv").write_text(
            (base / "fixtures" / "case-001" / "events.csv").read_text()
            + "\nEXTRA,2026-09-11T09:00:00,X,,,day\n")
        findings = verify_receipt(record["receipt_id"], base_dir=base,
                                  receipts_dir=rdir)
        self.assertEqual(findings["checks"]["evidence"], "fail")


class AdjudicationTest(unittest.TestCase):
    def _tmp(self):
        import tempfile

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        return tmp

    def test_review_does_not_alter_receipt(self):
        tmp = self._tmp()
        record = write_receipt(valid_payload(), "low",
                               receipts_dir=Path(tmp) / "r")
        before = (Path(tmp) / "r" / record["receipt_id"] / "receipt.json").read_bytes()
        text = review_text(record["receipt_id"], receipts_dir=Path(tmp) / "r")
        self.assertIn("Review checklist", text)
        self.assertIn("7", text)  # eligible-case figure visible
        record_adjudication(record["receipt_id"], "accept",
                            "Quotes and numbers check out.", "eng",
                            receipts_dir=Path(tmp) / "r")
        after = (Path(tmp) / "r" / record["receipt_id"] / "receipt.json").read_bytes()
        self.assertEqual(before, after)
        adjudicated = load_receipt(record["receipt_id"], Path(tmp) / "r")
        self.assertEqual(adjudicated["adjudication_status"], "pending")

    def test_adjudication_recorded_separately(self):
        tmp = self._tmp()
        record = write_receipt(valid_payload(), None,
                               receipts_dir=Path(tmp) / "r")
        adjudication = record_adjudication(
            record["receipt_id"], "needs-work", "Re-check the anomaly.",
            "eng", receipts_dir=Path(tmp) / "r")
        self.assertEqual(adjudication["investigation_sha256"],
                         record["investigation_sha256"])
        stored = json.loads((Path(tmp) / "r" / record["receipt_id"]
                             / "adjudication.json").read_text())
        self.assertEqual(stored["decision"], "needs-work")

    def test_adjudication_requires_note(self):
        tmp = self._tmp()
        record = write_receipt(valid_payload(), None,
                               receipts_dir=Path(tmp) / "r")
        with self.assertRaises(ReceiptError):
            record_adjudication(record["receipt_id"], "accept", "  ", "eng",
                                receipts_dir=Path(tmp) / "r")


class PrivacyTest(unittest.TestCase):
    def test_no_secrets_or_private_eval_data(self):
        from backend.eval_private import gold_rationales

        tmp = __import__("tempfile").mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        record = write_receipt(valid_payload(), "low",
                               receipts_dir=Path(tmp) / "r")
        blob = json.dumps(record)
        for forbidden in ("Bearer", "MODEL_API_KEY", "Authorization"):
            self.assertNotIn(forbidden, blob)
        for rationale in gold_rationales("v1") + gold_rationales("v2"):
            self.assertNotIn(rationale, blob)

    def test_receipts_not_served_over_http(self):
        ctx = new_context()
        for target in ("/evaluator-private/receipts/abc/receipt.json",
                       "/../evaluator-private/receipts/abc/receipt.json",
                       "/evaluator-private/keys/EVAL-01.json"):
            status, _, _ = handle_request("GET", target, None, ctx)
            self.assertEqual(status, 404, msg=target)

    def test_receipts_dir_is_private(self):
        self.assertTrue(str(RECEIPTS_DIR).startswith(str(ROOT / "evaluator-private")))
        gitignore = (ROOT / ".gitignore").read_text()
        self.assertIn("evaluator-private/", gitignore)

    def test_no_network_during_receipt_lifecycle(self):
        import tempfile

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network used")):
            record = write_receipt(valid_payload(), "low",
                                   receipts_dir=Path(tmp) / "r")
            review_text(record["receipt_id"], receipts_dir=Path(tmp) / "r")
            verify_receipt(record["receipt_id"], receipts_dir=Path(tmp) / "r")
            record_adjudication(record["receipt_id"], "accept", "ok",
                                "eng", receipts_dir=Path(tmp) / "r")


if __name__ == "__main__":
    unittest.main()
