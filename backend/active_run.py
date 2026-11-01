"""Active-run pointer (MC-007.2).

Standalone offline component identifying which committed mission
snapshot is the live one after a restart. Standard library only; no
network, no model calls, no receipt linkage.

NOT imported or invoked by backend/server.py: persistence remains
disconnected. All functions take an explicit store directory and
create nothing implicitly.

Ordering rule (commit point): a snapshot generation is committed
first via mission_store.commit_snapshot; only then may the pointer
select it. The pointer replacement is the commit point of a persisted
transition: a snapshot without a pointer selecting it is quarantined,
never authoritative.

Operator states (PointerError.code doubles as the operator state):
  no-pointer, pointer-corrupt, unsupported-pointer, no-snapshot,
  revision-mismatch, identity-mismatch, stale-pointer, no-store.
Plain-language text lives in pointer_state_message().
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .mission_snapshot import RUN_RE, decode_snapshot
from .mission_store import StoreError, load_snapshot

SCHEMA = "ActiveRunPointerV1"
POINTER_FILENAME = "active-run.json"
FILE_MODE = 0o600

_MESSAGES = {
    "no-pointer": "No saved mission found. A new mission run can be started.",
    "pointer-corrupt": "Recovery required: the active-run pointer is "
                       "unreadable or malformed. Saved snapshots were not "
                       "touched; an operator must inspect and re-point.",
    "unsupported-pointer": "Recovery required: unsupported saved-state "
                           "version. The pointer schema is not recognized; "
                           "an operator must migrate or archive it.",
    "no-snapshot": "No saved mission found. A new mission run can be started.",
    "revision-mismatch": "Recovery required: active-run pointer mismatch. "
                         "The selected snapshot revision does not match the "
                         "committed selection; nothing was restored.",
    "identity-mismatch": "Recovery required: active-run pointer mismatch. "
                         "The stored snapshot belongs to a different mission "
                         "run; nothing was restored.",
    "stale-pointer": "Save failed; previous accepted state preserved. A "
                     "newer pointer selection already exists.",
    "no-store": "No saved mission found. A new mission run can be started.",
    "snapshot-invalid": "Recovery required: snapshot integrity failure. "
                        "The selected snapshot failed validation; nothing "
                        "was restored.",
}


class PointerError(ValueError):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def pointer_state_message(code: str) -> str:
    """Plain operator language for a pointer/resolution state code."""
    return _MESSAGES.get(code, f"Recovery required: unrecognized state ({code}).")


def _pointer_path(store_dir: str | Path) -> Path:
    root = Path(store_dir)
    if not root.is_dir():
        raise PointerError("snapshot store directory absent", "no-store")
    path = root / POINTER_FILENAME
    if path.is_symlink():
        raise PointerError("active-run pointer must not be a symlink",
                           "pointer-corrupt")
    return path


def _read_record(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PointerError(f"pointer unreadable: {exc}",
                           "pointer-corrupt") from exc
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PointerError("pointer bytes are not valid JSON",
                           "pointer-corrupt") from exc
    if not isinstance(record, dict):
        raise PointerError("pointer must be an object", "pointer-corrupt")
    if record.get("schema") != SCHEMA:
        raise PointerError("unsupported pointer schema version",
                           "unsupported-pointer")
    if not isinstance(record.get("mission_run_id"), str) \
            or not RUN_RE.match(record["mission_run_id"]):
        raise PointerError("pointer mission identity malformed",
                           "pointer-corrupt")
    rev = record.get("snapshot_revision")
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 1:
        raise PointerError("pointer revision malformed", "pointer-corrupt")
    prev = record.get("pointer_revision", 1)
    if not isinstance(prev, int) or isinstance(prev, bool) or prev < 1:
        raise PointerError("pointer sequence malformed", "pointer-corrupt")
    return record


def read_pointer(store_dir: str | Path) -> dict[str, Any]:
    """Read and validate the pointer without touching any snapshot."""
    path = _pointer_path(store_dir)
    if not path.is_file():
        raise PointerError("no active-run pointer stored", "no-pointer")
    return _read_record(path)


def _write_bytes(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise PointerError("active-run pointer must not be a symlink",
                           "pointer-corrupt")
    tmp = path.with_suffix(".json.tmp")
    try:
        fd = os.open(tmp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, FILE_MODE)
    except OSError as exc:
        raise PointerError(f"pointer write failed: {exc}",
                           "pointer-corrupt") from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise PointerError(f"pointer write failed: {exc}",
                           "pointer-corrupt") from exc
    try:
        os.chmod(path.with_suffix(".json.tmp"), FILE_MODE)
    except OSError:
        pass
    try:
        os.replace(tmp, path)
    except OSError as exc:
        raise PointerError(f"pointer replace failed: {exc}",
                           "pointer-corrupt") from exc
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


def write_pointer(store_dir: str | Path, run_id: str,
                  snapshot_revision: int,
                  expected_pointer_revision: int | None = None) -> dict[str, Any]:
    """Atomically select a committed snapshot generation.

    Refuses to select anything not already committed: the snapshot is
    loaded and its identity and revision must match exactly. Concurrent
    writers pass expected_pointer_revision; a stale writer aborts with
    "stale-pointer" and the newer selection is preserved.
    """
    if not isinstance(run_id, str) or not RUN_RE.match(run_id):
        raise PointerError("pointer mission identity malformed",
                           "pointer-corrupt")
    if not isinstance(snapshot_revision, int) \
            or isinstance(snapshot_revision, bool) \
            or snapshot_revision < 1:
        raise PointerError("pointer revision malformed", "pointer-corrupt")
    path = _pointer_path(store_dir)
    current_rev = 0
    if path.is_file():
        current = _read_record(path)
        current_rev = current.get("pointer_revision", 1)
        if current.get("mission_run_id") != run_id:
            raise PointerError(
                "pointer already selects a different mission run; "
                "explicit operator re-pointing required",
                "identity-mismatch")
    if expected_pointer_revision is not None \
            and expected_pointer_revision != current_rev:
        raise PointerError("a newer pointer selection already exists",
                           "stale-pointer")
    try:
        snapshot = load_snapshot(store_dir, run_id)
    except StoreError as exc:
        code = {"missing": "no-snapshot"}.get(exc.code, "snapshot-invalid")
        raise PointerError(f"cannot select snapshot: {exc}", code) from exc
    if snapshot.get("mission_run_id") != run_id:
        raise PointerError("snapshot belongs to a different mission run",
                           "identity-mismatch")
    if snapshot.get("snapshot_revision") != snapshot_revision:
        raise PointerError("snapshot revision does not match selection",
                           "revision-mismatch")
    record = {"schema": SCHEMA, "mission_run_id": run_id,
              "snapshot_revision": snapshot_revision,
              "pointer_revision": current_rev + 1}
    _write_bytes(path, json.dumps(record, sort_keys=True,
                                  separators=(",", ":")).encode("utf-8"))
    return record


def _previous_generation(store_dir: str | Path,
                         pointer: dict[str, Any]) -> dict[str, Any] | None:
    """The verified .prev generation, only if the pointer selects it.

    This is the crash-after-replace case: the main file moved on but the
    pointer still names the previous committed generation. Honoring it is
    explicit (pointer-selected and digest-verified), never a silent
    fallback to an arbitrary older state.
    """
    from .mission_snapshot import SnapshotError, decode_snapshot
    prev = (Path(store_dir)
            / f"mission-{pointer['mission_run_id']}.json.prev")
    if not prev.is_file() or prev.is_symlink():
        return None
    try:
        candidate = decode_snapshot(prev.read_bytes())
    except (OSError, SnapshotError):
        return None
    if candidate.get("mission_run_id") != pointer["mission_run_id"]:
        return None
    if candidate.get("snapshot_revision") != pointer["snapshot_revision"]:
        return None
    return candidate


def resolve_active(store_dir: str | Path) -> dict[str, Any]:
    """Return the live snapshot selected by the pointer.

    Returns {"pointer", "snapshot", "state": "restored", "quarantined"}
    where "quarantined" is the newer unselected revision when the
    pointer was honored from the previous generation (crash after
    snapshot replace, before pointer update), else None. Raises
    PointerError whose code is the operator state otherwise. Never
    restores an unselected snapshot.
    """
    pointer = read_pointer(store_dir)
    try:
        snapshot = load_snapshot(store_dir, pointer["mission_run_id"])
    except StoreError as exc:
        code = {"missing": "no-snapshot"}.get(exc.code, "snapshot-invalid")
        raise PointerError(f"selected snapshot unavailable: {exc}",
                           code) from exc
    if snapshot.get("mission_run_id") != pointer["mission_run_id"]:
        raise PointerError("snapshot belongs to a different mission run",
                           "identity-mismatch")
    if snapshot.get("snapshot_revision") != pointer["snapshot_revision"]:
        previous = _previous_generation(store_dir, pointer)
        if previous is None:
            raise PointerError("selected snapshot revision does not match",
                               "revision-mismatch")
        return {"pointer": pointer, "snapshot": previous,
                "state": "restored",
                "quarantined": snapshot.get("snapshot_revision")}
    return {"pointer": pointer, "snapshot": snapshot, "state": "restored",
            "quarantined": None}


def load_committed(store_dir: str | Path, run_id: str) -> dict[str, Any]:
    """Load a committed generation explicitly named by the operator.

    Used when valid snapshots exist with no active pointer (crash case
    12): the result is flagged "unpointed" and is never presented as the
    restored live mission until an explicit write_pointer selects it.
    """
    if not isinstance(run_id, str) or not RUN_RE.match(run_id):
        raise PointerError("pointer mission identity malformed",
                           "pointer-corrupt")
    try:
        snapshot = load_snapshot(store_dir, run_id)
    except StoreError as exc:
        code = {"missing": "no-snapshot"}.get(exc.code, "snapshot-invalid")
        raise PointerError(f"snapshot unavailable: {exc}", code) from exc
    return {"snapshot": snapshot, "state": "unpointed"}
