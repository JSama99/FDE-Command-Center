"""Local backup and restore verification (CP-002).

Copies a mission store's committed snapshot generations, active-run
pointer, and audit log into a timestamped backup directory with a
file-hash manifest; restores only into empty disposable directories
after re-verifying every byte. Standard library only.

Safety rules:
  - Backups never modify the source store.
  - A backup is accepted only if the pointer still selects the same
    revision after the copy (store-changed retry, never a torn set).
  - Restore refuses non-empty destinations (never silently overwrites
    operational data), corrupt/incomplete backups, mismatched hashes,
    and unsupported schema versions.
  - Restore replays nothing: files are copied, no transition runs,
    and concealed outcomes stay gated behind the normal resolve path.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .active_run import PointerError, resolve_active
from .mission_snapshot import SCHEMA as SNAPSHOT_SCHEMA

FILE_MODE = 0o600
DIR_MODE = 0o700
MANIFEST_FILENAME = "backup-manifest.json"


class BackupError(ValueError):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(src, "rb") as fin, open(dest, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    os.chmod(dest, FILE_MODE)


def create_backup(store_dir: str | Path, backup_root: str | Path,
                  label: str = "manual") -> dict[str, Any]:
    """Copy and verify a consistent backup. Returns the manifest."""
    store = Path(store_dir)
    if not store.is_dir():
        raise BackupError("mission store absent", "no-store")
    try:
        resolved = resolve_active(store)
    except PointerError as exc:
        raise BackupError(f"store not restorable, refusing backup: {exc}",
                          "unrestorable") from exc
    revision = resolved["snapshot"]["snapshot_revision"]
    run = resolved["pointer"]["mission_run_id"]
    dest = Path(backup_root) / f"{run}-r{revision}-{_now_stamp()}-{label}"
    if dest.exists():
        raise BackupError("backup destination exists", "exists")
    dest.mkdir(parents=True)
    os.chmod(dest, DIR_MODE)
    files: dict[str, str] = {}
    for path in sorted(store.iterdir()):
        if not path.is_file() or path.is_symlink():
            continue
        if not (path.name == "active-run.json"
                or path.name.startswith("mission-")
                or path.name == "audit.log"):
            continue
        target = dest / path.name
        _copy_file(path, target)
        files[path.name] = _sha256_file(target)
    # Consistency: the pointer must select the same revision after copy.
    try:
        rechecked = resolve_active(store)
    except PointerError as exc:
        raise BackupError(f"store changed during backup: {exc}",
                          "store-changed") from exc
    if rechecked["snapshot"]["snapshot_revision"] != revision or \
            rechecked["pointer"]["mission_run_id"] != run:
        raise BackupError("store changed during backup; retry",
                          "store-changed")
    manifest = {"schema": "MissionBackupV1", "mission_run_id": run,
                "snapshot_revision": revision,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "label": label, "files": files}
    manifest_path = dest / MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                             encoding="utf-8")
    os.chmod(manifest_path, FILE_MODE)
    return manifest


def inspect_backup(backup_dir: str | Path) -> dict[str, Any]:
    """Verify a backup without restoring it. Raises BackupError."""
    root = Path(backup_dir)
    manifest_path = root / MANIFEST_FILENAME
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise BackupError("backup manifest missing", "incomplete")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError("backup manifest unreadable", "corrupt") from exc
    if not isinstance(manifest, dict) \
            or manifest.get("schema") != "MissionBackupV1":
        raise BackupError("unsupported backup version",
                          "unsupported-version")
    if not isinstance(manifest.get("files"), dict) \
            or not manifest["files"]:
        raise BackupError("backup file list missing", "incomplete")
    for name, digest in manifest["files"].items():
        if "/" in name or name.startswith("."):
            raise BackupError(f"unsafe backup entry: {name}", "corrupt")
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise BackupError(f"backup file missing: {name}", "incomplete")
        if _sha256_file(path) != digest:
            raise BackupError(f"backup file corrupted: {name}", "corrupt")
    snapshot_names = [n for n in manifest["files"]
                      if n.startswith("mission-") and n.endswith(".json")]
    if not snapshot_names:
        raise BackupError("backup holds no snapshot", "incomplete")
    for name in snapshot_names:
        try:
            body = json.loads((root / name).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackupError(f"snapshot unreadable: {name}",
                              "corrupt") from exc
        if body.get("schema") != SNAPSHOT_SCHEMA:
            raise BackupError(f"unsupported snapshot version: {name}",
                              "unsupported-version")
        if body.get("mission_run_id") != manifest["mission_run_id"]:
            raise BackupError(f"snapshot identity mismatch: {name}",
                              "identity-mismatch")
    return manifest


def restore_backup(backup_dir: str | Path, dest_dir: str | Path) -> Path:
    """Restore a verified backup into an empty directory. No replay."""
    manifest = inspect_backup(backup_dir)
    dest = Path(dest_dir)
    if dest.exists() and any(dest.iterdir()):
        raise BackupError("destination is not empty; refusing to overwrite",
                          "dest-not-empty")
    dest.mkdir(parents=True, exist_ok=True)
    os.chmod(dest, DIR_MODE)
    for name in manifest["files"]:
        _copy_file(Path(backup_dir) / name, dest / name)
    return dest


__all__ = ["BackupError", "create_backup", "inspect_backup",
           "restore_backup"]
