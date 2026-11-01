"""Offline receipt-link registry (MC-008.2).

Validates and preserves provable mission-to-receipt associations.
Never manufactures one: every check recomputes from the stored
snapshot and receipt, and supplying matching identifiers is not proof.

Standard library only. No server import, no endpoints, no provider
calls, no receipt or snapshot mutation. Operates on explicit
directories; test callers pass temporary ones.

Link lifecycle statuses: "active" -> "superseded" (a newer link for
the same run) or "revoked" (operator withdrawal). Records are
append-only; nothing is edited or deleted.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "MissionReceiptLinkV1"
SCHEMA_VERSION = "1.1"
REGISTRY_FILENAME = "link-registry.json"
FILE_MODE = 0o600

EVENT_TYPES = ("post-assessment-link", "audit-view-link", "revision-link")
LINK_STATUSES = ("active", "superseded", "revoked")

MISSION_ID = "mission-case-001"
CASE_ID = "case-001"
EXPERIMENT_ID = "EXP-001"

import re as _re

RUN_RE = _re.compile(r"^mr-[0-9a-f]{16}$")
HEX64_RE = _re.compile(r"^[0-9a-f]{64}$")


class LinkError(ValueError):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _registry_path(links_dir: str | Path) -> Path:
    root = Path(links_dir)
    if not root.is_dir():
        raise LinkError("link registry directory absent", "no-registry")
    path = root / REGISTRY_FILENAME
    if path.is_symlink():
        raise LinkError("registry must not be a symlink", "corrupt")
    return path


def load_registry(links_dir: str | Path) -> dict[str, Any]:
    """Load and validate the registry. Missing file means empty."""
    path = _registry_path(links_dir)
    if not path.is_file():
        return {"schema": SCHEMA, "schema_version": SCHEMA_VERSION,
                "registry_revision": 0, "links": []}
    try:
        record = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LinkError("registry bytes unreadable", "corrupt") from exc
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        raise LinkError("unsupported registry schema", "unsupported-version")
    if record.get("schema_version") != SCHEMA_VERSION:
        raise LinkError("unsupported link contract version",
                        "unsupported-version")
    rev = record.get("registry_revision")
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 0:
        raise LinkError("registry revision malformed", "corrupt")
    links = record.get("links")
    if not isinstance(links, list):
        raise LinkError("registry links malformed", "corrupt")
    for entry in links:
        _check_link_shape(entry)
    return record


def _check_link_shape(entry: Any) -> None:
    if not isinstance(entry, dict):
        raise LinkError("link record malformed", "corrupt")
    for key in ("contract", "link_id", "mission_run_id", "mission_id",
                "case_id", "experiment_id", "prediction_sha256",
                "receipt_id", "receipt_investigation_sha256",
                "snapshot_revision", "proposal", "decision",
                "linked_at_utc", "link_authority", "link_event",
                "status", "superseded_by"):
        if key not in entry:
            raise LinkError(f"link record missing {key}", "corrupt")
    if entry.get("contract") != SCHEMA:
        raise LinkError("unsupported link contract", "unsupported-version")
    if entry.get("link_event") not in EVENT_TYPES:
        raise LinkError("unknown link event type", "unsupported-version")
    if entry.get("status") not in LINK_STATUSES:
        raise LinkError("unknown link status", "corrupt")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _epoch(value: Any) -> float:
    """Normalize an epoch int/float or ISO-8601 string to epoch seconds."""
    if isinstance(value, bool):
        raise LinkError("timestamp malformed", "bad-timestamp")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise LinkError("timestamp malformed", "bad-timestamp") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    raise LinkError("timestamp malformed", "bad-timestamp")


def _validated_snapshot(snapshot: Any) -> dict[str, Any]:
    """Full codec validation of the mission-side source record."""
    from .mission_snapshot import SnapshotError, decode_snapshot
    from .mission_snapshot import encode_snapshot

    if not isinstance(snapshot, dict):
        raise LinkError("mission snapshot malformed", "bad-snapshot")
    try:
        return decode_snapshot(encode_snapshot(snapshot))
    except SnapshotError as exc:
        raise LinkError(f"mission snapshot invalid: {exc}",
                        "bad-snapshot") from exc


def _validated_receipt(receipt: Any) -> dict[str, Any]:
    """Integrity check of the receipt-side source record."""
    if not isinstance(receipt, dict):
        raise LinkError("receipt malformed", "bad-receipt")
    for key in ("receipt_id", "created_at_utc", "case_id",
                "investigation_sha256", "investigation"):
        if key not in receipt:
            raise LinkError(f"receipt missing {key}", "bad-receipt")
    if not isinstance(receipt.get("receipt_id"), str) \
            or not receipt["receipt_id"]:
        raise LinkError("receipt identity malformed", "bad-receipt")
    stored = _sha256(_canonical(receipt["investigation"]))
    if stored != receipt["investigation_sha256"]:
        raise LinkError("receipt integrity failure", "integrity-fail")
    return receipt


def _event_gate(event: str, snapshot: dict[str, Any]) -> None:
    """Event-specific lifecycle prerequisites on the run's snapshot."""
    experiment_ready = snapshot.get("assessment") is not None
    if event == "post-assessment-link" and not experiment_ready:
        raise LinkError("run is not assessed; post-assessment link refused",
                        "event-not-ready")
    mission = snapshot.get("mission") or {}
    if event == "audit-view-link" and not (
            mission.get("diagnostic") == "timestamp-audit"
            and mission.get("audit_viewed") is True):
        raise LinkError("timestamp audit not viewed; audit link refused",
                        "event-not-ready")
    if event == "revision-link":
        validation = snapshot.get("revision_validation") or {}
        if snapshot.get("revision") is None \
                or validation.get("decision") != "approve":
            raise LinkError("no approved revision; revision link refused",
                            "event-not-ready")


def _provenance_check(receipt: dict[str, Any], base_dir: Any) -> None:
    """Full investigation validation against current fixtures.

    Integrity proves self-consistency only; this re-verifies every
    citation and number against the evidence registry and pins the
    receipt to the current source manifest. A self-consistent forgery
    with bogus references fails here.
    """
    from .investigation import build_evidence_registry, validate_investigation
    from .receipt import evidence_manifest
    from .report import build_case_report

    try:
        registry = build_evidence_registry(build_case_report(base_dir))
        validate_investigation(receipt["investigation"], registry)
    except Exception as exc:  # noqa: BLE001 - any validation failure refuses
        raise LinkError(f"receipt provenance failed: {type(exc).__name__}",
                        "provenance-fail") from exc
    try:
        current = evidence_manifest(base_dir)
    except OSError as exc:
        raise LinkError(f"source evidence unavailable: {exc}",
                        "bad-snapshot") from exc
    if receipt.get("evidence_manifest") != current:
        raise LinkError("receipt evidence manifest drifted",
                        "provenance-fail")


def check_binding(snapshot: dict[str, Any], receipt: dict[str, Any],
                  event: str, base_dir: Any = None) -> dict[str, Any]:
    """Recompute every cross-record check. Returns binding evidence.

    Raises LinkError naming the first failed check. Matching
    identifiers alone never pass: hashes, case, event gates, temporal
    order, and full provenance must all recompute green.
    """
    from pathlib import Path as _Path

    snapshot = _validated_snapshot(snapshot)
    receipt = _validated_receipt(receipt)
    _provenance_check(receipt, _Path(base_dir) if base_dir is not None
                      else _Path(__file__).resolve().parents[1])
    if event not in EVENT_TYPES:
        raise LinkError(f"unknown link event type: {event}",
                        "unsupported-version")
    _event_gate(event, snapshot)
    if receipt.get("case_id") != snapshot.get("case_id"):
        raise LinkError("receipt case does not match run case",
                        "case-mismatch")
    prediction = snapshot.get("prediction") or {}
    if prediction:
        recomputed = _sha256(_canonical(
            {k: v for k, v in prediction.items() if k != "hash"}))
        if prediction.get("hash") != recomputed:
            raise LinkError("locked prediction hash does not recompute",
                            "prediction-mismatch")
        if _epoch(receipt["created_at_utc"]) < _epoch(
                prediction.get("locked_at")):
            raise LinkError("receipt predates the locked prediction",
                            "temporal-violation")
    # Timestamp-audit runs never lock a prediction; their binding rests
    # on run identity, case, event gate, and provenance instead.
    intervention = snapshot.get("intervention") or {}
    proposal = intervention.get("proposal") if intervention else None
    return {
        "mission_run_id": snapshot["mission_run_id"],
        "prediction_sha256": prediction.get("hash"),
        "receipt_investigation_sha256": receipt["investigation_sha256"],
        "snapshot_revision": snapshot["snapshot_revision"],
        "proposal": ({"proposal_id": proposal.get("proposal_id"),
                      "version": proposal.get("version")}
                     if isinstance(proposal, dict) else None),
        "decision": intervention.get("decision") if intervention else None,
    }


def _write_registry(links_dir: str | Path, record: dict[str, Any]) -> None:
    path = _registry_path(links_dir)
    tmp = path.with_suffix(".json.tmp")
    if tmp.is_symlink() or path.is_symlink():
        raise LinkError("registry must not be a symlink", "corrupt")
    try:
        fd = os.open(tmp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, FILE_MODE)
    except OSError as exc:
        raise LinkError(f"registry write failed: {exc}",
                        "write-failed") from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            data = json.dumps(record, sort_keys=True,
                              separators=(",", ":")).encode("utf-8")
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise LinkError(f"registry write failed: {exc}",
                        "write-failed") from exc
    try:
        os.chmod(tmp, FILE_MODE)
    except OSError:
        pass
    try:
        os.replace(tmp, path)
    except OSError as exc:
        raise LinkError(f"registry replace failed: {exc}",
                        "write-failed") from exc
    try:
        fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def create_link(links_dir: str | Path, snapshot: dict[str, Any],
                receipt: dict[str, Any], event: str, operator: str,
                expected_registry_revision: int | None = None,
                base_dir: Any = None) -> dict:
    """Create and store a verified link. Raises LinkError otherwise.

    There is no override: any failed check refuses creation. A second
    active link for the same run supersedes the first (append-only).
    """
    if not isinstance(operator, str) or not operator.strip():
        raise LinkError("link operator identity required", "bad-operator")
    binding = check_binding(snapshot, receipt, event, base_dir)
    registry = load_registry(links_dir)
    if expected_registry_revision is not None and \
            expected_registry_revision != registry["registry_revision"]:
        raise LinkError("a newer registry revision already exists",
                        "stale-registry")
    for entry in registry["links"]:
        if entry["mission_run_id"] == binding["mission_run_id"] \
                and entry["status"] == "active":
            entry["status"] = "superseded"
    record = {
        "contract": SCHEMA,
        "link_id": uuid.uuid4().hex[:16],
        "mission_run_id": binding["mission_run_id"],
        "mission_id": MISSION_ID,
        "case_id": snapshot["case_id"],
        "experiment_id": EXPERIMENT_ID,
        "prediction_sha256": binding["prediction_sha256"],
        "receipt_id": receipt["receipt_id"],
        "receipt_investigation_sha256":
            binding["receipt_investigation_sha256"],
        "snapshot_revision": binding["snapshot_revision"],
        "proposal": binding["proposal"],
        "decision": binding["decision"],
        "linked_at_utc": datetime.now(timezone.utc).isoformat(),
        "link_authority": "human-operator",
        "link_operator": operator.strip()[:120],
        "link_event": event,
        "status": "active",
        "superseded_by": None,
    }
    superseded = [e["link_id"] for e in registry["links"]
                  if e["mission_run_id"] == binding["mission_run_id"]
                  and e["status"] == "superseded" and not e["superseded_by"]]
    for entry in registry["links"]:
        if entry["link_id"] in superseded:
            entry["superseded_by"] = record["link_id"]
    _check_link_shape(record)
    registry["links"].append(record)
    registry["registry_revision"] += 1
    _write_registry(links_dir, registry)
    return record


def revoke_link(links_dir: str | Path, link_id: str, operator: str,
                expected_registry_revision: int | None = None) -> dict:
    """Withdraw a link. The record is preserved with status revoked."""
    if not isinstance(operator, str) or not operator.strip():
        raise LinkError("link operator identity required", "bad-operator")
    registry = load_registry(links_dir)
    if expected_registry_revision is not None and \
            expected_registry_revision != registry["registry_revision"]:
        raise LinkError("a newer registry revision already exists",
                        "stale-registry")
    for entry in registry["links"]:
        if entry["link_id"] == link_id:
            if entry["status"] == "revoked":
                raise LinkError("link already revoked", "already-revoked")
            entry["status"] = "revoked"
            entry["revoked_by"] = operator.strip()[:120]
            entry["revoked_at_utc"] = datetime.now(timezone.utc).isoformat()
            registry["registry_revision"] += 1
            _write_registry(links_dir, registry)
            return entry
    raise LinkError("unknown link id", "unknown-link")


def verify_link(record: dict[str, Any], snapshot: dict[str, Any],
                receipt: dict[str, Any],
                base_dir: Any = None) -> dict[str, Any]:
    """Read-time revalidation. Returns verified/rejected with reasons."""
    try:
        _check_link_shape(record)
    except LinkError as exc:
        return {"link_id": (record or {}).get("link_id"),
                "state": "rejected", "reasons": [exc.code]}
    if record.get("status") == "revoked":
        return {"link_id": record["link_id"], "state": "rejected",
                "reasons": ["revoked"]}
    if record.get("status") == "superseded":
        return {"link_id": record["link_id"], "state": "rejected",
                "reasons": ["superseded"]}
    try:
        binding = check_binding(snapshot, receipt, record["link_event"],
                                base_dir)
    except LinkError as exc:
        return {"link_id": record["link_id"], "state": "rejected",
                "reasons": [exc.code]}
    mismatches = []
    notes = []
    for key in ("mission_run_id", "prediction_sha256",
                "receipt_investigation_sha256"):
        if record.get(key) != binding.get(key):
            mismatches.append(f"{key}-mismatch")
    # Locks, assessments, and receipts are immutable, so binding evidence
    # is stable across later revisions of the same run: a newer snapshot
    # still verifies (noted), an older one is stale (rejected).
    rec_rev = record.get("snapshot_revision")
    snap_rev = binding.get("snapshot_revision")
    if snap_rev != rec_rev:
        if not isinstance(snap_rev, int) or not isinstance(rec_rev, int) \
                or snap_rev < rec_rev:
            mismatches.append("stale-revision")
        else:
            notes.append("advanced-revision")
    current = snapshot.get("intervention") or {}
    current_proposal = current.get("proposal")
    if record.get("proposal") is not None and current_proposal is not None:
        if record["proposal"].get("proposal_id") != current_proposal.get(
                "proposal_id") or record["proposal"].get("version") != \
                current_proposal.get("version"):
            mismatches.append("proposal-mismatch")
    if record.get("decision") is not None and current.get("decision") \
            is not None and record.get("decision") != current.get("decision"):
        mismatches.append("decision-mismatch")
    if receipt.get("receipt_id") != record.get("receipt_id"):
        mismatches.append("receipt-mismatch")
    if mismatches:
        return {"link_id": record["link_id"], "state": "rejected",
                "reasons": mismatches}
    return {"link_id": record["link_id"], "state": "verified",
            "reasons": notes}


def _load_inputs(args) -> tuple[dict, dict]:
    """Load mission snapshot and receipt from explicit local paths."""
    from .mission_store import StoreError, load_snapshot
    from .receipt import ReceiptError, load_receipt

    try:
        snapshot = load_snapshot(args.store_dir, args.run_id)
    except StoreError as exc:
        raise LinkError(f"mission snapshot unavailable: {exc}",
                        "bad-snapshot") from exc
    try:
        receipt = load_receipt(args.receipt_id,
                               receipts_dir=args.receipts_dir)
    except ReceiptError as exc:
        raise LinkError(f"receipt unavailable: {exc}",
                        "bad-receipt") from exc
    except OSError as exc:
        raise LinkError(f"receipt unreadable: {exc}",
                        "bad-receipt") from exc
    return snapshot, receipt


def main(argv: list[str] | None = None) -> int:
    """Offline operator CLI. Prints a result line; 0 verified/ok,
    1 rejected or failed check, 2 unusable invocation or corrupt store."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Offline mission-receipt link registry (no server).")
    parser.add_argument("--links-dir", required=True)
    parser.add_argument("--receipts-dir", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--store-dir", required=True)
    create.add_argument("--run-id", required=True)
    create.add_argument("--receipt-id", required=True)
    create.add_argument("--event", required=True)
    create.add_argument("--operator", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--store-dir", required=True)
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--receipt-id", required=True)
    verify.add_argument("--link-id", required=True)
    revoke = sub.add_parser("revoke")
    revoke.add_argument("--link-id", required=True)
    revoke.add_argument("--operator", required=True)
    sub.add_parser("inspect")
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            registry = load_registry(args.links_dir)
            print(f"links: {len(registry['links'])} "
                  f"revision: {registry['registry_revision']}")
            for entry in registry["links"]:
                print(f"{entry['link_id']} {entry['mission_run_id']} "
                      f"{entry['receipt_id']} {entry['link_event']} "
                      f"{entry['status']}")
            return 0
        if args.command == "revoke":
            entry = revoke_link(args.links_dir, args.link_id,
                                args.operator)
            print(f"revoked: {entry['link_id']}")
            return 0
        snapshot, receipt = _load_inputs(args)
        if args.command == "create":
            record = create_link(args.links_dir, snapshot, receipt,
                                 args.event, args.operator)
            print(f"linked: {record['link_id']} "
                  f"{record['mission_run_id']} -> "
                  f"{record['receipt_id']} ({record['link_event']})")
            return 0
        registry = load_registry(args.links_dir)
        matches = [e for e in registry["links"]
                   if e["link_id"] == args.link_id]
        if not matches:
            print(f"rejected: unknown-link {args.link_id}")
            return 1
        result = verify_link(matches[0], snapshot, receipt)
        print(f"{result['state']}: {result['link_id']} "
              f"{','.join(result['reasons']) or 'all checks pass'}")
        return 0 if result["state"] == "verified" else 1
    except LinkError as exc:
        print(f"rejected: {exc.code} {exc}")
        return 1
    except (OSError, ValueError) as exc:
        print(f"error: {type(exc).__name__} {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
