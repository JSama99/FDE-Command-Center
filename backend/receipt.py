"""Private investigation receipts and offline human adjudication (Task 009.7a).

A receipt is a reproducible, private evidence-review artifact for one already
completed, backend-validated investigation. All metadata recorded here is
locally supplied (hashes, timestamps, configuration as configured) — never
claimed as provider-attested.

Storage: evaluator-private/receipts/<receipt_id>/ (gitignored, unserved,
restrictive permissions). No credentials, headers, reasoning content, or
transport bodies are ever written. No network use: writing, review, and
adjudication are fully offline.

Human adjudication is recorded in a separate file and never modifies the
original receipt. Automated validation and human acceptance stay distinct:
the receipt carries the validator result; the adjudication file carries the
reviewer's decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .investigation import (
    build_case_report,
    build_evidence_registry,
    produce_investigation,
    validate_investigation,
)
from .meta_adapter import (INVESTIGATION_REASONING_EFFORT, MAX_OUTPUT_TOKENS,
                           MODEL_ID)

ROOT = Path(__file__).resolve().parents[1]
RECEIPTS_DIR = ROOT / "evaluator-private" / "receipts"

REVIEW_CHECKLIST = (
    "1. Evidence fidelity and quotation accuracy",
    "2. Calculations and provenance",
    "3. Distinctness of competing hypotheses",
    "4. Diagnostic experiment quality and falsifiability",
    "5. Uncertainty and unsupported causal claims",
    "6. Human-approval and no-execution safeguards",
)


class ReceiptError(ValueError):
    pass


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validator_code_sha() -> str:
    return hashlib.sha256(
        (ROOT / "backend" / "investigation.py").read_bytes()).hexdigest()


def evidence_manifest(base_dir: str | Path = ROOT) -> dict:
    """Hashes of the synthetic source evidence behind case-001."""
    base = Path(base_dir)
    names = ("policy.md", "dispatcher.md", "manager.md", "events.csv")
    manifest = {}
    for name in names:
        data = (base / "fixtures" / "case-001" / name).read_bytes()
        manifest[f"fixtures/case-001/{name}"] = hashlib.sha256(data).hexdigest()
    return manifest


def write_receipt(investigation: dict, reasoning_effort: str | None = None,
                  base_dir: str | Path = ROOT,
                  receipts_dir: str | Path = RECEIPTS_DIR) -> dict:
    """Persist a receipt for an already completed investigation.

    The investigation is revalidated against a freshly built registry first;
    anything failing validation is refused. Returns the receipt record.
    """
    base = Path(base_dir)
    report = build_case_report(base)
    registry = build_evidence_registry(report)
    validated = validate_investigation(investigation, registry)
    receipt_id = uuid.uuid4().hex[:16]
    now = datetime.now(timezone.utc).isoformat()
    receipt = {
        "receipt_id": receipt_id,
        "created_at_utc": now,
        "case_id": report["case_id"],
        "synthetic": True,
        "model_config": {
            "model": MODEL_ID,
            "mode": "standard",
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "reasoning_effort": reasoning_effort,
            "provenance": "locally recorded configuration, not provider-attested",
        },
        "investigation_sha256": _sha256_text(_canonical(validated)),
        "evidence_manifest": evidence_manifest(base),
        "investigation": validated,
        "validation": {
            "result": "accepted",
            "validator": "backend.investigation.validate_investigation",
            "validator_code_sha256": validator_code_sha(),
            "note": "Automated validation only; not human acceptance.",
        },
        "adjudication_status": "pending",
    }
    receipt_dir = Path(receipts_dir) / receipt_id
    receipt_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(receipt_dir, 0o700)
    path = receipt_dir / "receipt.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return receipt


def load_receipt(receipt_id: str,
                 receipts_dir: str | Path = RECEIPTS_DIR) -> dict:
    path = Path(receipts_dir) / receipt_id / "receipt.json"
    if not path.is_file():
        raise ReceiptError(f"unknown receipt: {receipt_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def verify_receipt(receipt_id: str, base_dir: str | Path = ROOT,
                   receipts_dir: str | Path = RECEIPTS_DIR) -> dict:
    """Independently revalidate a stored receipt offline. Returns a report;
    never modifies the receipt."""
    receipt = load_receipt(receipt_id, receipts_dir)
    findings: dict = {"receipt_id": receipt_id, "checks": {}}
    # Historical integrity: does the stored content still hash to the recorded
    # value? Pure byte comparison — independent of any validator version.
    stored_hash = _sha256_text(_canonical(receipt["investigation"]))
    findings["checks"]["integrity"] = (
        "pass" if stored_hash == receipt["investigation_sha256"] else "fail")
    code_match = (validator_code_sha()
                  == receipt["validation"]["validator_code_sha256"])
    findings["checks"]["validator_code"] = (
        "match" if code_match else "changed-since-issue")
    try:
        report = build_case_report(Path(base_dir))
        registry = build_evidence_registry(report)
        validate_investigation(receipt["investigation"], registry)
        findings["checks"]["revalidation"] = "pass"
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        findings["checks"]["revalidation"] = f"fail: {type(exc).__name__}"
    # Schema status separates history from current rules: a receipt issued
    # under older rules that no longer revalidates is version drift, never
    # evidence that it was originally invalid.
    if findings["checks"]["revalidation"] == "pass":
        findings["checks"]["schema-status"] = "current"
    elif not code_match:
        findings["checks"]["schema-status"] = "validator-version-drift"
    else:
        findings["checks"]["schema-status"] = "invalid-under-issued-rules"
    try:
        live_manifest = evidence_manifest(base_dir)
        findings["checks"]["evidence"] = (
            "pass" if live_manifest == receipt["evidence_manifest"] else "fail")
    except Exception:  # noqa: BLE001 - unreadable evidence fails the check
        findings["checks"]["evidence"] = "fail"
    findings["checks"]["validator_code"] = (
        "match" if validator_code_sha() == receipt["validation"]["validator_code_sha256"]
        else "changed-since-issue")
    findings["adjudication_status"] = receipt["adjudication_status"]
    return findings


def review_text(receipt_id: str, base_dir: str | Path = ROOT,
                receipts_dir: str | Path = RECEIPTS_DIR) -> str:
    """Human-readable review rendering: stored investigation plus the source
    evidence behind it and the six-point checklist. Read-only."""
    receipt = load_receipt(receipt_id, receipts_dir)
    report = build_case_report(Path(base_dir))
    lines = [
        f"Receipt {receipt['receipt_id']} ({receipt['created_at_utc']})",
        f"Case {receipt['case_id']} · model {receipt['model_config']['model']} "
        f"(reasoning effort {receipt['model_config']['reasoning_effort']})",
        f"Investigation sha256: {receipt['investigation_sha256']}",
        f"Adjudication status: {receipt['adjudication_status']}",
        "",
        "--- Validated investigation ---",
    ]
    inv = receipt["investigation"]
    for obs in inv.get("observations", []):
        lines.append(f"[{obs.get('basis')}] {obs.get('text')} (refs: {', '.join(obs.get('refs', []))})")
    for hyp in inv.get("competing_hypotheses", []):
        lines.append(f"[hypothesis] {hyp.get('text')}")
    for key in ("unresolved_questions",):
        for item in inv.get(key, []):
            lines.append(f"[open] {item}")
    rec = inv.get("provisional_recommendation", {})
    lines.append(f"[recommendation] {rec.get('text')} "
                 f"(approval required: {rec.get('requires_human_approval')}, "
                 f"executes change: {rec.get('executes_production_change')})")
    lines.append("")
    lines.append("--- Source evidence (synthetic fixtures) ---")
    for calc in report["calculations"]:
        lines.append(f"{calc['label']}: {calc['value']} "
                     f"(denominator: {calc['denominator']}; rule: {calc['rule']})")
    lines.append("")
    lines.append("--- Review checklist ---")
    lines.extend(REVIEW_CHECKLIST)
    return "\n".join(lines) + "\n"


def record_adjudication(receipt_id: str, decision: str, note: str,
                        reviewer: str,
                        receipts_dir: str | Path = RECEIPTS_DIR) -> dict:
    """Record a reviewer's decision in a separate file. The original receipt
    is never modified."""
    if decision not in ("accept", "reject", "needs-work"):
        raise ReceiptError(f"unknown decision: {decision}")
    if not str(note).strip():
        raise ReceiptError("an adjudication note is required")
    receipt = load_receipt(receipt_id, receipts_dir)
    path = Path(receipts_dir) / receipt_id / "adjudication.json"
    if path.is_file():
        raise ReceiptError(
            "an adjudication record already exists; historical human review "
            "is never overwritten")
    adjudication = {
        "receipt_id": receipt_id,
        "investigation_sha256": receipt["investigation_sha256"],
        "decision": decision,
        "note": str(note).strip()[:2000],
        "reviewer": str(reviewer)[:120] or "unidentified",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    path = Path(receipts_dir) / receipt_id / "adjudication.json"
    path.write_text(json.dumps(adjudication, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return adjudication


def produce_investigation_with_receipt(adapter, base_dir: str | Path = ROOT,
                                           receipts_dir: str | Path = RECEIPTS_DIR) -> dict:
    """Run one investigation and receipt it. The model is invoked exactly
    once via produce_investigation(); the receipt is issued directly from the
    validated in-memory result — no intermediate files. Receipt creation is
    opt-in: existing produce_investigation() callers are unaffected.

    Returns only the receipt id, storage location, validation status, and a
    non-sensitive summary. If receipt writing fails, the failure is reported
    alongside the preserved investigation; no second model call is made.
    """
    result = produce_investigation(adapter, base_dir)
    investigation = result["investigation"]
    summary = {
        "case_id": result["case_id"],
        "model": MODEL_ID,
        "observations": len(investigation.get("observations", [])),
        "competing_hypotheses": len(investigation.get("competing_hypotheses", [])),
        "unresolved_questions": len(investigation.get("unresolved_questions", [])),
    }
    try:
        receipt = write_receipt(
            investigation, INVESTIGATION_REASONING_EFFORT, base_dir, receipts_dir)
    except Exception as exc:  # noqa: BLE001 - reported with investigation kept
        return {"receipt_id": None,
                "receipt_error": f"{type(exc).__name__}: {exc}",
                "validation": "accepted",
                "summary": summary,
                "investigation": investigation}
    storage = str(Path(receipts_dir) / receipt["receipt_id"] / "receipt.json")
    return {"receipt_id": receipt["receipt_id"],
            "storage": storage,
            "validation": "accepted",
            "summary": summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline investigation receipts.")
    sub = parser.add_subparsers(dest="command", required=True)
    issue = sub.add_parser("issue", help="Write a receipt for validated JSON.")
    issue.add_argument("validated_json", help="Path to validated investigation JSON.")
    issue.add_argument("--reasoning-effort", default=None)
    review = sub.add_parser("review", help="Display a receipt for human review.")
    review.add_argument("receipt_id")
    adj = sub.add_parser("adjudicate", help="Record a human decision.")
    adj.add_argument("receipt_id")
    adj.add_argument("decision", choices=("accept", "reject", "needs-work"))
    adj.add_argument("--note", required=True)
    adj.add_argument("--reviewer", default="")
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except ReceiptError as exc:
        print(f"receipt error: {exc}")
        return 1


def _run(args: argparse.Namespace) -> int:
    if args.command == "issue":
        payload = json.loads(Path(args.validated_json).read_text(encoding="utf-8"))
        receipt = write_receipt(payload, args.reasoning_effort)
        print(f"receipt: {receipt['receipt_id']}")
        return 0
    if args.command == "review":
        print(review_text(args.receipt_id), end="")
        return 0
    record = record_adjudication(args.receipt_id, args.decision, args.note, args.reviewer)
    print(f"adjudication: {record['decision']} on {record['receipt_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
