"""Durable mission persistence bridge (MC-007.3).

Connects the offline snapshot store (mission_store) and active-run
pointer (active_run) to live server state. Standard library only.

Protocol per accepted transition, executed under the server's
transition lock:
  1. Run the existing domain transition on an isolated deep copy.
  2. If the accepted state is unchanged, acknowledge without writing.
  3. Otherwise commit snapshot revision N+1 (CAS against N), then
     advance the pointer to N+1. The pointer replacement is the commit
     point: only then is the live state swapped and success acked.
  4. Any failure before the pointer replacement returns failure and
     leaves live state untouched. Snapshot committed but pointer
     failed -> degraded mode: reads continue, mutations are refused,
     restart reconciles via the proven lineage rule or aborts.

Startup (boot_context): no pointer/snapshot -> fresh run (nothing
created implicitly). Valid selection -> exact restore. Pointer
selects an older generation while a verified direct successor exists
-> adopt the successor explicitly and report it. Anything else ->
abort startup with the operator message; never silently start fresh
over unresolved persisted state.

Restore performs zero transitions: records are copied verbatim and
experiment status is re-derived from record presence.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .active_run import (PointerError, pointer_state_message, read_pointer,
                         resolve_active, write_pointer)
from .experiment import new_experiment_state
from .mission import new_mission_state
from .mission_snapshot import build_snapshot
from .mission_store import StoreError, commit_snapshot, load_snapshot
from .receipt import evidence_manifest

STORE_ENV_VAR = "FDE_MISSION_STORE"
DEFAULT_STORE_DIRNAME = "mission-snapshots"


class PersistenceError(ValueError):
    """Durable-acceptance failure. Live state was left untouched."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def resolve_store_dir(explicit: str | Path | None = None) -> Path:
    """Configured private storage location with a safe default.

    Nothing is created here: creation happens only on the first
    accepted commit, inside mission_store.
    """
    configured = explicit if explicit is not None else os.environ.get(
        STORE_ENV_VAR)
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[1] / DEFAULT_STORE_DIRNAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _manifest(base_dir: Any) -> dict[str, str]:
    try:
        return evidence_manifest(base_dir)
    except OSError as exc:
        raise PersistenceError(f"source evidence unavailable: {exc}",
                               "persistence-failed") from exc


def fresh_context(base_dir: Any, store_dir: str | Path) -> dict[str, Any]:
    """A new in-memory run. Creates no files."""
    return {
        "base_dir": Path(base_dir),
        "approvals": [],
        "diagnostics": [],
        "experiment": new_experiment_state(),
        "mission": new_mission_state(),
        "_store_dir": str(store_dir),
        "_snapshot_revision": 0,
        "_persistence_degraded": False,
    }


def _derive_status(snapshot: dict[str, Any]) -> str:
    if snapshot.get("assessment") is not None:
        return "assessed"
    if snapshot.get("outcome") is not None:
        return "result revealed"
    if snapshot.get("prediction") is not None:
        return "prediction locked"
    return "proposed"


def apply_snapshot(snapshot: dict[str, Any], base_dir: Any,
                   store_dir: str | Path, revision: int) -> dict[str, Any]:
    """Rebuild live state from a validated snapshot. No transitions run."""
    ctx = fresh_context(base_dir, store_dir)
    mission = ctx["mission"]
    mission["mission_run_id"] = snapshot["mission_run_id"]
    mission["diagnostic"] = snapshot["mission"]["diagnostic"]
    mission["audit_viewed"] = snapshot["mission"]["audit_viewed"]
    mission["intervention"] = snapshot["intervention"]
    experiment = ctx["experiment"]
    experiment["status"] = _derive_status(snapshot)
    experiment["prediction"] = snapshot["prediction"]
    experiment["outcome"] = snapshot["outcome"]
    experiment["assessment"] = snapshot["assessment"]
    experiment["revision"] = snapshot["revision"]
    experiment["revision_validation"] = snapshot["revision_validation"]
    ctx["approvals"] = [dict(a) for a in snapshot["approvals"]]
    ctx["_snapshot_revision"] = revision
    return ctx


def boot_context(base_dir: Any,
                 store_dir: str | Path | None = None) -> tuple[dict, str, str]:
    """Startup restoration.

    Returns (ctx, status, message) where status is "fresh", "restored",
    or "abort". "abort" means the process must not serve: the message
    is the actionable operator text.
    """
    store = Path(store_dir) if store_dir is not None \
        else resolve_store_dir()
    if not store.is_dir():
        return fresh_context(base_dir, store), "fresh", \
            "No saved mission found. Starting a new mission run."
    try:
        resolved = resolve_active(store)
    except PointerError as exc:
        if exc.code in ("no-pointer", "no-store"):
            return fresh_context(base_dir, store), "fresh", \
                "No saved mission found. Starting a new mission run."
        return {}, "abort", pointer_state_message(exc.code)
    snapshot = resolved["snapshot"]
    if snapshot.get("source_manifest") != _manifest(base_dir):
        return {}, "abort", \
            "Recovery required: source evidence changed since the mission " \
            "was saved. The saved run is preserved; an operator must " \
            "archive it and start a new run over the current fixtures."
    if resolved.get("quarantined") is not None:
        # Proven lineage only: the main file moved exactly one step past
        # the pointer and .prev matches the selection. Adopt explicitly.
        try:
            selected = load_snapshot(store,
                                     resolved["pointer"]["mission_run_id"])
        except StoreError:
            return {}, "abort", pointer_state_message("snapshot-invalid")
        if selected.get("snapshot_revision") != resolved["quarantined"]:
            return {}, "abort", pointer_state_message("revision-mismatch")
        try:
            write_pointer(store, selected["mission_run_id"],
                          selected["snapshot_revision"])
        except PointerError as exc:
            return {}, "abort", pointer_state_message(exc.code)
        ctx = apply_snapshot(selected, base_dir, store,
                             selected["snapshot_revision"])
        return ctx, "restored", \
            f"Mission restored at revision {selected['snapshot_revision']} " \
            f"after adopting the committed successor of the previous " \
            f"selection (run {selected['mission_run_id']})."
    ctx = apply_snapshot(snapshot, base_dir, store,
                         snapshot["snapshot_revision"])
    return ctx, "restored", \
        f"Mission {snapshot['mission_run_id']} restored at revision " \
        f"{snapshot['snapshot_revision']}."


def _comparable(ctx: dict[str, Any], manifest: dict[str, str]) -> dict:
    body = build_snapshot(ctx, manifest, 1, "compare")
    return {k: v for k, v in body.items()
            if k not in ("snapshot_revision", "saved_at_utc")}


def commit_transition(live: dict[str, Any], work: dict[str, Any]) -> int:
    """Durably accept work's state into live. Returns new revision.

    Raises PersistenceError without touching live on any failure. On a
    pointer failure after a committed snapshot, live is flagged
    degraded (reads continue, mutations refused) so restart can
    reconcile; the committed-but-unpointed generation is never
    silently promoted.
    """
    store = Path(live.get("_store_dir") or resolve_store_dir())
    manifest = _manifest(live.get("base_dir"))
    try:
        changed = _comparable(work, manifest) != _comparable(live, manifest)
    except Exception as exc:  # noqa: BLE001 - fail closed, never ack blindly
        raise PersistenceError(f"snapshot construction failed: {exc}",
                               "persistence-failed") from exc
    if not changed:
        live.clear()
        live.update(work)
        return int(live.get("_snapshot_revision", 0))
    base = int(live.get("_snapshot_revision", 0))
    run_id = live["mission"]["mission_run_id"]
    body = build_snapshot(work, manifest, base + 1, _now())
    try:
        committed = commit_snapshot(store, run_id, body, base)
    except (StoreError, Exception) as exc:  # noqa: BLE001 - fail closed
        code = exc.code if isinstance(exc, StoreError) else \
            "persistence-failed"
        raise PersistenceError(f"durable commit failed ({code}); previous "
                               f"accepted state preserved", code) from exc
    try:
        write_pointer(store, run_id, committed)
    except PointerError as exc:
        live["_persistence_degraded"] = True
        raise PersistenceError(
            f"pointer advancement failed ({exc.code}); the transition was "
            f"committed but is NOT active. Reads continue; mutations are "
            f"refused until restart reconciles. Previous accepted state "
            f"preserved", exc.code) from exc
    work["_snapshot_revision"] = committed
    work["_persistence_degraded"] = False
    live.clear()
    live.update(work)
    return committed


__all__ = ["PersistenceError", "apply_snapshot", "boot_context",
           "commit_transition", "fresh_context", "pointer_state_message",
           "resolve_store_dir"]
