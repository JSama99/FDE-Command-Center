"""Atomic MissionSnapshotV1 storage (MC-004f).

Production-quality, standard-library-only durable store for validated
snapshots. Uses backend.mission_snapshot for all validation; this
module adds only files, ordering, and failure semantics.

NOT connected to server startup, transitions, or any API route: all
functions take an explicit store directory, and importing this module
creates nothing. No network operations.

A digest detects accidental or unkeyed modification; it is not
encryption, authentication, or tenant isolation, and local file
permissions do not constitute either.
"""

from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .mission_snapshot import RUN_RE, SnapshotError, decode_snapshot

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platforms
    fcntl = None  # type: ignore[assignment]

DIR_MODE = 0o700
FILE_MODE = 0o600
# Suggested future location only; never created implicitly.
DEFAULT_STORE_DIRNAME = "mission-snapshots"


class StoreError(ValueError):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _check_run_id(run_id: str) -> None:
    if not isinstance(run_id, str) or not RUN_RE.match(run_id):
        raise StoreError("mission run identity malformed", "bad-identity")


def _paths(store_dir: str | Path, run_id: str) -> tuple[Path, Path, Path, Path]:
    _check_run_id(run_id)
    root = Path(store_dir)
    return (root / f"mission-{run_id}.json",
            root / f"mission-{run_id}.json.prev",
            root / f"mission-{run_id}.json.tmp",
            root / ".lock")


def _ensure_dir(root: Path) -> None:
    try:
        root.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    except OSError as exc:
        raise StoreError(f"store directory unavailable: {exc}",
                         "store-unavailable") from exc
    try:
        if stat.S_IMODE(root.stat().st_mode) != DIR_MODE:
            os.chmod(root, DIR_MODE)
    except OSError as exc:
        raise StoreError(f"store directory permissions failed: {exc}",
                         "permissions") from exc


@contextmanager
def _locked(root: Path):
    _ensure_dir(root)
    lock_path = root / ".lock"
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, FILE_MODE)
    except OSError as exc:
        raise StoreError(f"store lock unavailable: {exc}",
                         "store-unavailable") from exc
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _write_file(path: Path, data: bytes) -> None:
    try:
        fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, FILE_MODE)
    except OSError as exc:
        raise StoreError(f"snapshot write failed: {exc}", "write-failed") from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise StoreError(f"snapshot write failed: {exc}", "write-failed") from exc
    try:
        os.chmod(path, FILE_MODE)
    except OSError as exc:
        raise StoreError(f"snapshot permissions failed: {exc}",
                         "permissions") from exc


def _fsync_dir(root: Path) -> None:
    try:
        fd = os.open(root, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def commit_snapshot(store_dir: str | Path, run_id: str,
                    body: dict[str, Any], expected_revision: int) -> int:
    """Atomically publish a validated snapshot generation.

    Steps: validate the candidate; load and validate the current
    revision; compare-and-swap; stage privately; replace; confirm by
    reloading. Anything failing before the replace leaves prior state
    untouched; a confirm failure afterwards raises explicitly and is
    never reported as success.
    """
    from .mission_snapshot import encode_snapshot

    main, prev, tmp, _ = _paths(store_dir, run_id)
    root = main.parent
    candidate = encode_snapshot(body)
    try:
        decode_snapshot(candidate)
    except SnapshotError as exc:
        raise StoreError(f"candidate snapshot invalid: {exc}",
                         "invalid-candidate") from exc
    with _locked(root):
        current_rev = -1
        current_raw: bytes | None = None
        if main.is_file():
            try:
                current_raw = main.read_bytes()
            except OSError as exc:
                raise StoreError(f"current snapshot unreadable: {exc}",
                                 "read-failed") from exc
            try:
                current_rev = decode_snapshot(current_raw)["snapshot_revision"]
            except SnapshotError as exc:
                raise StoreError(f"current snapshot invalid: {exc}",
                                 "current-invalid") from exc
        base = current_rev if main.is_file() else 0
        if expected_revision != base:
            raise StoreError(
                f"stale revision: writer based on {expected_revision}, "
                f"committed {base if main.is_file() else 'none'}",
                "stale-revision")
        if body["snapshot_revision"] != base + 1:
            raise StoreError(
                f"non-monotonic revision: body carries "
                f"{body['snapshot_revision']}, expected {base + 1}",
                "bad-revision")
        _write_file(tmp, candidate)
        if current_raw is not None:
            _write_file(prev, current_raw)
        try:
            os.replace(tmp, main)
        except OSError as exc:
            raise StoreError(f"atomic replace failed: {exc}",
                             "replace-failed") from exc
        _fsync_dir(root)
        try:
            confirmed = decode_snapshot(main.read_bytes())
        except (OSError, SnapshotError) as exc:
            raise StoreError(f"commit confirm failed: {exc}",
                             "confirm-failed") from exc
        return confirmed["snapshot_revision"]


def load_snapshot(store_dir: str | Path, run_id: str) -> dict[str, Any]:
    """Load and validate the committed generation. Never falls back."""
    main, _, _, _ = _paths(store_dir, run_id)
    if not main.is_file():
        raise StoreError("no snapshot stored for this run", "missing")
    try:
        raw = main.read_bytes()
    except OSError as exc:
        raise StoreError(f"snapshot unreadable: {exc}", "read-failed") from exc
    try:
        return decode_snapshot(raw)
    except SnapshotError as exc:
        raise StoreError(f"stored snapshot invalid: {exc}",
                         "current-invalid") from exc


def inspect_snapshot_status(store_dir: str | Path,
                            run_id: str) -> tuple[str, str]:
    """Fail-closed status without leaking snapshot contents.

    Returns (state, category) where state is one of "ok", "missing", or
    "recovery-required". A corrupt current generation is never
    silently replaced by the previous one.
    """
    try:
        main, _, _, _ = _paths(store_dir, run_id)
    except StoreError:
        return "recovery-required", "bad-identity"
    if not main.is_file():
        return "missing", "no-snapshot"
    try:
        raw = main.read_bytes()
    except OSError:
        return "recovery-required", "read-failed"
    try:
        decode_snapshot(raw)
    except SnapshotError as exc:
        return "recovery-required", exc.code
    return "ok", "current"
