"""MC-008.2: receipt-link registry tests.

Offline only, temporary directories. Synthetic test receipts are
derived read-only from stored content and labeled as fixtures; they
are never presented as historical associations. No provider calls,
no receipt/snapshot mutation, no server changes.
"""

import copy
import hashlib
import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend import link_registry
from backend.link_registry import LinkError, main as cli
from backend.mission_snapshot import build_snapshot
from backend.persistence import boot_context
from backend.receipt import evidence_manifest
from backend.server import handle_request

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL = ["10d84a313fd44022", "1902c485a31f4e45"]
PREDICTION = {
    "hypothesis_id": "H-ACK", "expected_finding": "ack-found",
    "expected_observation": "Source holds a case-003 ack missing.",
    "criteria": "ack-found supports H-ACK.",
    "refs": ["case-003", "events.csv"],
}


def call(ctx, method, target, body=None):
    raw = None if body is None else json.dumps(body).encode("utf-8")
    return handle_request(method, target, raw, ctx)


def assessed_snapshot(case, store, choice="feed-probe"):
    ctx, status, _ = boot_context(ROOT, store)
    case.assertEqual(status, "fresh")
    call(ctx, "POST", "/api/mission/diagnostic", {"choice": choice})
    if choice == "feed-probe":
        call(ctx, "POST", "/api/experiment/predict", PREDICTION)
        call(ctx, "POST", "/api/experiment/reveal", None)
        call(ctx, "POST", "/api/experiment/assess", None)
    else:
        call(ctx, "GET", "/api/mission/diagnostic/result")
    from backend.mission_store import load_snapshot

    run = ctx["mission"]["mission_run_id"]
    return ctx, load_snapshot(store, run)


def test_receipt(case, **overrides):
    base = json.loads((ROOT / "evaluator-private" / "receipts" /
                       HISTORICAL[0] / "receipt.json").read_text())
    receipt = {
        "receipt_id": "test-%s" % os.urandom(6).hex(),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_id": "case-001",
        "synthetic": True,
        "synthetic_test_fixture": True,
        "model_config": base["model_config"],
        "evidence_manifest": evidence_manifest(ROOT),
        "investigation": copy.deepcopy(base["investigation"]),
        "validation": base["validation"],
        "adjudication_status": "pending",
    }
    receipt.update(overrides)
    receipt["investigation_sha256"] = link_registry._sha256(
        link_registry._canonical(receipt["investigation"]))
    return receipt


class ValidLinkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.links = Path(self.tmp.name) / "links"
        self.links.mkdir()
        self.store = Path(self.tmp.name) / "store"

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_and_verify_post_assessment_link(self):
        ctx, snapshot = assessed_snapshot(self, str(self.store))
        receipt = test_receipt(self)
        record = link_registry.create_link(
            str(self.links), snapshot, receipt,
            "post-assessment-link", "operator", base_dir=ROOT)
        self.assertEqual(record["status"], "active")
        self.assertEqual(record["mission_run_id"],
                         ctx["mission"]["mission_run_id"])
        self.assertEqual(record["receipt_id"], receipt["receipt_id"])
        self.assertEqual(record["link_event"], "post-assessment-link")
        result = link_registry.verify_link(record, snapshot, receipt,
                                           base_dir=ROOT)
        self.assertEqual(result, {"link_id": record["link_id"],
                                  "state": "verified", "reasons": []})

    def test_cli_create_verify_inspect(self):
        ctx, snapshot = assessed_snapshot(self, str(self.store))
        receipt = test_receipt(self)
        # CLI loads from store/receipt dirs; stage a receipts dir instead.
        rdir = Path(self.tmp.name) / "receipts" / receipt["receipt_id"]
        rdir.mkdir(parents=True)
        (rdir / "receipt.json").write_text(json.dumps(receipt))
        base = ["--links-dir", str(self.links), "--receipts-dir",
                str(Path(self.tmp.name) / "receipts")]
        self.assertEqual(cli(base + ["create", "--store-dir", str(self.store),
                                     "--run-id",
                                     ctx["mission"]["mission_run_id"],
                                     "--receipt-id", receipt["receipt_id"],
                                     "--event", "post-assessment-link",
                                     "--operator", "cli-op"]), 0)
        record = link_registry.load_registry(
            str(self.links))["links"][0]
        self.assertEqual(cli(base + ["verify", "--store-dir",
                                     str(self.store), "--run-id",
                                     ctx["mission"]["mission_run_id"],
                                     "--receipt-id", receipt["receipt_id"],
                                     "--link-id", record["link_id"]]), 0)
        self.assertEqual(cli(base + ["inspect"]), 0)

    def test_audit_view_link(self):
        _, snapshot = assessed_snapshot(self, str(self.store),
                                        choice="timestamp-audit")
        receipt = test_receipt(self)
        record = link_registry.create_link(
            str(self.links), snapshot, receipt, "audit-view-link",
            "operator", base_dir=ROOT)
        self.assertEqual(record["link_event"], "audit-view-link")

    def test_revision_link_requires_approval(self):
        ctx, _ = assessed_snapshot(self, str(self.store))
        call(ctx, "POST", "/api/revision/generate", {"mode": "mock"})
        from backend.mission_store import load_snapshot

        snapshot = load_snapshot(str(self.store),
                                 ctx["mission"]["mission_run_id"])
        receipt = test_receipt(self)
        with self.assertRaises(LinkError) as cm:
            link_registry.create_link(str(self.links), snapshot, receipt,
                                      "revision-link", "operator",
                                      base_dir=ROOT)
        self.assertEqual(cm.exception.code, "event-not-ready")
        call(ctx, "POST", "/api/revision/approve",
             {"decision": "approve", "note": "Evidence-bound."})
        snapshot = load_snapshot(str(self.store),
                                 ctx["mission"]["mission_run_id"])
        record = link_registry.create_link(
            str(self.links), snapshot, receipt, "revision-link",
            "operator", base_dir=ROOT)
        self.assertEqual(record["status"], "active")

    def test_pre_decision_link_survives_later_decision(self):
        ctx, snapshot = assessed_snapshot(self, str(self.store))
        receipt = test_receipt(self)
        record = link_registry.create_link(
            str(self.links), snapshot, receipt, "post-assessment-link",
            "operator", base_dir=ROOT)
        self.assertIsNone(record["decision"])
        _, proposal, _ = call(ctx, "GET", "/api/mission/proposal")
        call(ctx, "POST", "/api/mission/intervention", {
            "decision": "approve", "note": "Smallest step.",
            "proposal_id": proposal["proposal_id"],
            "proposal_version": proposal["version"]})
        from backend.mission_store import load_snapshot

        newer = load_snapshot(str(self.store),
                              ctx["mission"]["mission_run_id"])
        result = link_registry.verify_link(record, newer, receipt,
                                           base_dir=ROOT)
        self.assertEqual(result["state"], "verified")
        self.assertEqual(result["reasons"], ["advanced-revision"])
        future = copy.deepcopy(record)
        future["snapshot_revision"] = newer["snapshot_revision"] + 1
        result = link_registry.verify_link(future, newer, receipt,
                                           base_dir=ROOT)
        self.assertEqual(result["state"], "rejected")
        self.assertIn("stale-revision", result["reasons"])

    def test_second_link_supersedes_first(self):
        _, snapshot = assessed_snapshot(self, str(self.store))
        first = link_registry.create_link(
            str(self.links), snapshot, test_receipt(self),
            "post-assessment-link", "op-a", base_dir=ROOT)
        second = link_registry.create_link(
            str(self.links), snapshot, test_receipt(self),
            "post-assessment-link", "op-b", base_dir=ROOT)
        registry = link_registry.load_registry(str(self.links))
        by_id = {e["link_id"]: e for e in registry["links"]}
        self.assertEqual(by_id[first["link_id"]]["status"], "superseded")
        self.assertEqual(by_id[first["link_id"]]["superseded_by"],
                         second["link_id"])
        self.assertEqual(link_registry.verify_link(
            by_id[first["link_id"]], snapshot, test_receipt(self),
            base_dir=ROOT)["reasons"], ["superseded"])

    def test_revoke_preserves_record(self):
        _, snapshot = assessed_snapshot(self, str(self.store))
        receipt = test_receipt(self)
        record = link_registry.create_link(
            str(self.links), snapshot, receipt, "post-assessment-link",
            "operator", base_dir=ROOT)
        entry = link_registry.revoke_link(str(self.links),
                                          record["link_id"], "operator")
        self.assertEqual(entry["status"], "revoked")
        result = link_registry.verify_link(entry, snapshot, receipt,
                                           base_dir=ROOT)
        self.assertEqual(result["state"], "rejected")
        self.assertEqual(result["reasons"], ["revoked"])
        with self.assertRaises(LinkError) as cm:
            link_registry.revoke_link(str(self.links), record["link_id"],
                                      "operator")
        self.assertEqual(cm.exception.code, "already-revoked")


class HistoricalNegativeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.links = Path(self.tmp.name) / "links"
        self.links.mkdir()
        self.store = Path(self.tmp.name) / "store"

    def tearDown(self):
        self.tmp.cleanup()

    def load_historical(self, rid):
        return json.loads((ROOT / "evaluator-private" / "receipts" /
                           rid / "receipt.json").read_text())

    def test_historical_receipts_cannot_link(self):
        _, snapshot = assessed_snapshot(self, str(self.store))
        codes = set()
        for rid in HISTORICAL:
            with self.assertRaises(LinkError) as cm:
                link_registry.create_link(
                    str(self.links), snapshot, self.load_historical(rid),
                    "post-assessment-link", "operator", base_dir=ROOT)
            codes.add(cm.exception.code)
        # 10d84 validates but predates the run; 1902 fails current rules.
        self.assertEqual(codes, {"temporal-violation", "provenance-fail"})
        self.assertEqual(link_registry.load_registry(
            str(self.links))["links"], [])

    def test_missing_mission_identity_refused(self):
        _, snapshot = assessed_snapshot(self, str(self.store))
        broken = copy.deepcopy(snapshot)
        del broken["mission_run_id"]
        with self.assertRaises(LinkError) as cm:
            link_registry.create_link(str(self.links), broken,
                                      test_receipt(self),
                                      "post-assessment-link", "operator",
                                      base_dir=ROOT)
        self.assertEqual(cm.exception.code, "bad-snapshot")

    def test_timestamp_only_proves_nothing(self):
        _, snapshot = assessed_snapshot(self, str(self.store))
        receipt = test_receipt(self)
        receipt["investigation_sha256"] = "0" * 64  # hash no longer matches
        with self.assertRaises(LinkError) as cm:
            link_registry.create_link(str(self.links), snapshot, receipt,
                                      "post-assessment-link", "operator",
                                      base_dir=ROOT)
        self.assertEqual(cm.exception.code, "integrity-fail")

    def test_case_name_only_proves_nothing(self):
        _, snapshot = assessed_snapshot(self, str(self.store))
        receipt = test_receipt(self, case_id="case-999")
        with self.assertRaises(LinkError) as cm:
            link_registry.create_link(str(self.links), snapshot, receipt,
                                      "post-assessment-link", "operator",
                                      base_dir=ROOT)
        self.assertEqual(cm.exception.code, "case-mismatch")

    def test_unassessed_run_refuses_assessment_link(self):
        ctx, _, _ = boot_context(ROOT, str(self.store))
        call(ctx, "POST", "/api/mission/diagnostic", {"choice": "feed-probe"})
        from backend.mission_store import load_snapshot

        snapshot = load_snapshot(str(self.store),
                                 ctx["mission"]["mission_run_id"])
        with self.assertRaises(LinkError) as cm:
            link_registry.create_link(str(self.links), snapshot,
                                      test_receipt(self),
                                      "post-assessment-link", "operator",
                                      base_dir=ROOT)
        self.assertEqual(cm.exception.code, "event-not-ready")

    def test_execution_is_not_an_event(self):
        self.assertNotIn("execut", " ".join(link_registry.EVENT_TYPES))
        _, snapshot = assessed_snapshot(self, str(self.store))
        with self.assertRaises(LinkError) as cm:
            link_registry.create_link(str(self.links), snapshot,
                                      test_receipt(self),
                                      "approval-executed", "operator",
                                      base_dir=ROOT)
        self.assertEqual(cm.exception.code, "unsupported-version")

    def test_forged_references_refused(self):
        _, snapshot = assessed_snapshot(self, str(self.store))
        receipt = test_receipt(self)
        receipt["investigation"]["observations"].append(
            {"text": "Forged: supplier outage caused everything.",
             "refs": ["nonexistent-doc"]})
        receipt["investigation_sha256"] = link_registry._sha256(
            link_registry._canonical(receipt["investigation"]))
        with self.assertRaises(LinkError) as cm:
            link_registry.create_link(str(self.links), snapshot, receipt,
                                      "post-assessment-link", "operator",
                                      base_dir=ROOT)
        self.assertEqual(cm.exception.code, "provenance-fail")

    def test_corrupt_receipt_refused(self):
        _, snapshot = assessed_snapshot(self, str(self.store))
        with self.assertRaises(LinkError) as cm:
            link_registry.create_link(str(self.links), snapshot,
                                      {"receipt_id": ""},
                                      "post-assessment-link", "operator",
                                      base_dir=ROOT)
        self.assertEqual(cm.exception.code, "bad-receipt")

    def test_link_record_claims_no_execution(self):
        _, snapshot = assessed_snapshot(self, str(self.store))
        record = link_registry.create_link(
            str(self.links), snapshot, test_receipt(self),
            "post-assessment-link", "operator", base_dir=ROOT)
        blob = json.dumps(record).lower()
        self.assertNotIn("execut", blob)


class RegistryIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.links = Path(self.tmp.name) / "links"
        self.links.mkdir()
        self.store = Path(self.tmp.name) / "store"

    def tearDown(self):
        self.tmp.cleanup()

    def valid_pair(self):
        _, snapshot = assessed_snapshot(self, str(self.store))
        return snapshot, test_receipt(self)

    def test_stale_registry_revision_rejected(self):
        snapshot, receipt = self.valid_pair()
        link_registry.create_link(str(self.links), snapshot, receipt,
                                  "post-assessment-link", "op",
                                  base_dir=ROOT)
        with self.assertRaises(LinkError) as cm:
            link_registry.create_link(str(self.links), snapshot,
                                      test_receipt(self),
                                      "post-assessment-link", "op",
                                      expected_registry_revision=0,
                                      base_dir=ROOT)
        self.assertEqual(cm.exception.code, "stale-registry")

    def test_concurrent_writers_one_wins(self):
        snapshot, receipt = self.valid_pair()
        first = link_registry.create_link(
            str(self.links), snapshot, receipt, "post-assessment-link",
            "op-a", expected_registry_revision=0, base_dir=ROOT)
        with self.assertRaises(LinkError) as cm:
            link_registry.create_link(
                str(self.links), snapshot, test_receipt(self),
                "post-assessment-link", "op-b", expected_registry_revision=0,
                base_dir=ROOT)
        self.assertEqual(cm.exception.code, "stale-registry")
        registry = link_registry.load_registry(str(self.links))
        self.assertEqual(len(registry["links"]), 1)
        self.assertEqual(registry["links"][0]["link_id"], first["link_id"])

    def test_corrupt_registry_detected(self):
        (self.links / "link-registry.json").write_bytes(b"corrupt{")
        with self.assertRaises(LinkError) as cm:
            link_registry.load_registry(str(self.links))
        self.assertEqual(cm.exception.code, "corrupt")

    def test_symlink_registry_refused(self):
        target = self.links / "real.json"
        target.write_text("{}")
        try:
            (self.links / "link-registry.json").symlink_to(target)
        except OSError:
            self.skipTest("symlinks unsupported here")
        with self.assertRaises(LinkError) as cm:
            link_registry.load_registry(str(self.links))
        self.assertEqual(cm.exception.code, "corrupt")

    def test_unsupported_registry_schema(self):
        (self.links / "link-registry.json").write_text(json.dumps(
            {"schema": "MissionReceiptLinkV9"}))
        with self.assertRaises(LinkError) as cm:
            link_registry.load_registry(str(self.links))
        self.assertEqual(cm.exception.code, "unsupported-version")

    def test_read_time_tamper_detected(self):
        snapshot, receipt = self.valid_pair()
        record = link_registry.create_link(
            str(self.links), snapshot, receipt, "post-assessment-link",
            "op", base_dir=ROOT)
        tampered = copy.deepcopy(receipt)
        tampered["investigation"]["observations"].append(
            {"text": "Inserted after linking.", "refs": ["policy"]})
        result = link_registry.verify_link(record, snapshot, tampered,
                                           base_dir=ROOT)
        self.assertEqual(result["state"], "rejected")
        self.assertIn("integrity-fail", result["reasons"])

    def test_wrong_proposal_version_detected(self):
        ctx, snapshot = assessed_snapshot(self, str(self.store))
        _, proposal, _ = call(ctx, "GET", "/api/mission/proposal")
        call(ctx, "POST", "/api/mission/intervention", {
            "decision": "approve", "note": "Step.",
            "proposal_id": proposal["proposal_id"],
            "proposal_version": proposal["version"]})
        from backend.mission_store import load_snapshot

        decided = load_snapshot(str(self.store),
                                ctx["mission"]["mission_run_id"])
        record = link_registry.create_link(
            str(self.links), decided, test_receipt(self),
            "post-assessment-link", "op", base_dir=ROOT)
        altered = copy.deepcopy(decided)
        altered["intervention"]["proposal"]["version"] = "v9"
        # Re-sign the altered snapshot so the codec accepts it.
        import backend.mission_snapshot as codec

        resigned = codec.decode_snapshot(codec.encode_snapshot(altered))
        result = link_registry.verify_link(record, resigned,
                                           test_receipt(self),
                                           base_dir=ROOT)
        self.assertEqual(result["state"], "rejected")
        self.assertIn("proposal-mismatch", result["reasons"])

    def test_sources_byte_identical_after_all_operations(self):
        snapshot, receipt = self.valid_pair()
        snap_hash = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        for rid in HISTORICAL:
            path = (ROOT / "evaluator-private" / "receipts" / rid /
                    "receipt.json")
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            record = link_registry.create_link(
                str(self.links), snapshot, test_receipt(self),
                "post-assessment-link", "op", base_dir=ROOT)
            link_registry.verify_link(record, snapshot, receipt,
                                      base_dir=ROOT)
            link_registry.revoke_link(str(self.links), record["link_id"],
                                      "op")
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(before, after, msg=rid)
        self.assertEqual(hashlib.sha256(
            json.dumps(snapshot, sort_keys=True).encode()).hexdigest(),
            snap_hash)

    def test_registry_permissions_restrictive(self):
        snapshot, receipt = self.valid_pair()
        link_registry.create_link(str(self.links), snapshot, receipt,
                                  "post-assessment-link", "op",
                                  base_dir=ROOT)
        mode = stat.S_IMODE((self.links / "link-registry.json").stat()
                            .st_mode)
        self.assertEqual(mode, 0o600)


class SecurityRegressionTest(unittest.TestCase):
    def test_no_server_or_frontend_changes(self):
        server_src = (ROOT / "backend" / "server.py").read_text()
        self.assertNotIn("link_registry", server_src)
        self.assertNotIn("MissionReceiptLinkV1", server_src)
        self.assertNotIn("/api/link", server_src)

    def test_registry_module_is_offline(self):
        import re

        src = (ROOT / "backend" / "link_registry.py").read_text()
        imported = {name.split(".")[0] for name in re.findall(
            r"^\s*(?:import|from)\s+(\S+)", src, re.M)}
        for token in ("meta_adapter", "socket", "subprocess", "urllib",
                      "http", "ssl", "server", "chaos_simulation"):
            self.assertNotIn(token, imported, msg=token)
        self.assertNotIn("MODEL_API_KEY", src)

    def test_zero_verified_historical_links(self):
        import tempfile

        from backend.link_registry import verify_link

        with tempfile.TemporaryDirectory() as tmp:
            links = Path(tmp) / "links"
            links.mkdir()
            _, snapshot = assessed_snapshot(
                self, str(Path(tmp) / "store"))
            for rid in HISTORICAL:
                receipt = json.loads(
                    (ROOT / "evaluator-private" / "receipts" / rid /
                     "receipt.json").read_text())
                try:
                    link_registry.create_link(
                        str(links), snapshot, receipt,
                        "post-assessment-link", "operator", base_dir=ROOT)
                    self.fail(f"historical receipt linked: {rid}")
                except LinkError:
                    pass


if __name__ == "__main__":
    unittest.main()
