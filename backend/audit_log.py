"""Bounded local audit log (CP-002).

Append-only JSONL lifecycle records for a single-user local pilot.
Observability only: the log is never authority, never tamper-proof,
and never evidence of truth.

Privacy rules (enforced by construction — record() accepts only
allowlisted metadata fields):
  logged: event type, outcome, timestamp, mission run id, snapshot
    revision, transition category, rejection/failure code.
  never: credentials, request/response bodies, investigation content,
    prompts, provider output, receipts, human rationales, uploads,
    customer information.

Failure policy: a failed audit write never fails the request it
describes. On the durable-accept path the server degrades future
mutations (existing degraded mode) instead of acknowledging silently;
on reject/boot paths the failure goes to stderr. Either way the
persistence commit contract is unchanged.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "AuditRecordV1"
FILENAME = "audit.log"
FILE_MODE = 0o600

OUTCOMES = ("accepted", "rejected", "failed", "degraded", "started")


class AuditError(ValueError):
    pass


def _record(event: str, outcome: str, mission_run_id: str | None,
            snapshot_revision: int | None, category: str,
            code: str | None) -> dict[str, Any]:
    if outcome not in OUTCOMES:
        raise AuditError(f"unknown audit outcome: {outcome}")
    if not isinstance(event, str) or not event:
        raise AuditError("audit event required")
    return {
        "schema": SCHEMA,
        "at": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "outcome": outcome,
        "mission_run_id": mission_run_id,
        "snapshot_revision": snapshot_revision,
        "category": category,
        "code": code,
    }


def append(store_dir: str | Path, event: str, outcome: str,
           mission_run_id: str | None = None,
           snapshot_revision: int | None = None,
           category: str = "mission-transition",
           code: str | None = None) -> dict[str, Any]:
    """Append one metadata-only record. Raises AuditError on failure."""
    record = _record(event, outcome, mission_run_id, snapshot_revision,
                     category, code)
    root = Path(store_dir)
    if not root.is_dir():
        raise AuditError("audit store directory absent")
    path = root / FILENAME
    if path.is_symlink():
        raise AuditError("audit log must not be a symlink")
    data = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
    try:
        fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY,
                     FILE_MODE)
    except OSError as exc:
        raise AuditError(f"audit log unavailable: {exc}") from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise AuditError(f"audit write failed: {exc}") from exc
    try:
        os.chmod(path, FILE_MODE)
    except OSError:
        pass
    return record


def read_all(store_dir: str | Path) -> list[dict[str, Any]]:
    """Read records for inspection. Skips malformed lines explicitly."""
    path = Path(store_dir) / FILENAME
    if not path.is_file() or path.is_symlink():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("schema") == SCHEMA:
            records.append(record)
    return records
