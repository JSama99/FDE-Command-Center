"""Isolated repair-and-retest harness (MC-005f).

Applies allowlisted synthetic repairs to in-memory copies of chaos-lab
fixtures, then independently re-evaluates with the same deterministic
yardstick used for fault detection. Standard library only; no network,
no subprocesses, no credentials, no model calls, no writes anywhere.

Only these production repairs exist:
- CHS-ASSIGN-01 + restore-assignments (remove the injected +300min shift)
- CHS-ACK-01 + reconcile-feed (copy exact source acks into the feed)

CHS-WINDOW-01 has no allowlisted repair: extending a window is not an
established correction, so it yields not-tested. Adversarial repairs
(no-op, deletion, duplication, reordering, unrelated edits, hiding)
exist only as test-local mutations passed to evaluate_repair — never
as runnable repairs.

A repaired fixture is not automatically a verified recovery: verified
requires the target condition resolved AND every regression check
passing AND byte-level restoration where applicable.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = "ChaosRecoveryResultV1"
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "chaos-lab"
FIXTURE_ID = "fixtures/chaos-lab"
ASSIGN_LIMIT_MIN = 60
ACK_LIMIT_MIN = 240
SHIFT_MINUTES = 300

ALLOWLIST = {
    ("CHS-ASSIGN-01", "restore-assignments"): "Remove the injected +300 minute assignment shift.",
    ("CHS-ACK-01", "reconcile-feed"): "Copy exact source acknowledgments into the feed.",
}


class ChaosRecoveryError(ValueError):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fixture_digest() -> str:
    blobs = [(FIXTURE_DIR / n).read_bytes()
             for n in ("ack_feed.csv", "ack_source.csv", "assign.csv",
                       "window.csv")]
    return _sha256(b"".join(blobs))


def _read_csv(name: str) -> list[dict[str, str]]:
    with open(FIXTURE_DIR / name, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _parse_ts(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    return datetime.fromisoformat(raw) if raw else None


def measure_assign(rows: list[dict[str, str]]) -> dict[str, dict]:
    """Same deterministic yardstick as the simulation engine."""
    measured = {}
    for row in rows:
        created = _parse_ts(row["created_at"])
        assigned = _parse_ts(row.get("assigned_at", ""))
        ack = _parse_ts(row.get("ack_at", ""))
        close = _parse_ts(row["window_close_at"])
        delay = ((assigned - created).total_seconds() / 60
                 if assigned and created else None)
        window_complete = (close is not None and created is not None
                           and (close - created).total_seconds() / 60 >= ACK_LIMIT_MIN)
        anomaly = ((assigned and created and assigned < created)
                   or (ack and created and ack < created)
                   or (ack and assigned and ack < assigned))
        ack_valid = bool(ack and created
                         and (ack - created).total_seconds() / 60 <= ACK_LIMIT_MIN
                         and not anomaly)
        if anomaly:
            classification = "anomalous-needs-source-check"
        elif not window_complete:
            classification = "incomplete"
        elif not ack_valid:
            classification = "confirmed-miss"
        else:
            classification = "acknowledged"
        measured[row["case_id"]] = {
            "assign_delay_min": delay,
            "breaches_1h": delay is not None and delay > ASSIGN_LIMIT_MIN,
            "window_complete": window_complete,
            "ordering_anomaly": bool(anomaly),
            "ack_valid": ack_valid,
            "classification": classification,
        }
    return measured


def measure_feed(source: dict[str, str],
                 feed: dict[str, str]) -> dict[str, dict]:
    return {case: {"source_ack": source.get(case),
                   "feed_ack": feed.get(case),
                   "discrepancy": source.get(case) != feed.get(case)}
            for case in sorted(set(source) | set(feed))}


def apply_repair(scenario_id: str, repair_id: str,
                 data: dict) -> tuple[dict, list[str]]:
    """Apply one allowlisted repair to an isolated copy. Returns the
    repaired data and the exact synthetic changes made."""
    if (scenario_id, repair_id) not in ALLOWLIST:
        raise ChaosRecoveryError(
            f"unknown scenario/repair pairing: {scenario_id}/{repair_id}",
            "unknown-pairing")
    changes: list[str] = []
    if scenario_id == "CHS-ASSIGN-01":
        rows = [dict(r) for r in data["rows"]]
        for row in rows:
            if row.get("assigned_at", "").strip():
                before = row["assigned_at"]
                shifted = _parse_ts(before) - timedelta(minutes=SHIFT_MINUTES)
                row["assigned_at"] = shifted.isoformat()
                changes.append(f"{row['case_id']} assigned_at "
                               f"{before}->{row['assigned_at']}")
        return {"rows": rows}, changes
    feed = dict(data["feed"])
    for case, ack in data["source"].items():
        if feed.get(case) != ack:
            changes.append(f"{case} feed_ack {feed.get(case)}->{ack}")
            feed[case] = ack
    return {"source": dict(data["source"]), "feed": feed}, changes


def evaluate_repair(scenario_id: str, repair_id: str, fault: str,
                    baseline: dict, faulted: dict, repaired: dict,
                    changes: list[str], note: str = "") -> dict:
    """Independently judge post-repair observations. `repaired` holds
    measurement dicts; raw-data comparisons arrive via `changes` plus
    the regression checks below."""
    regression: dict[str, bool] = {}
    if scenario_id == "CHS-ASSIGN-01":
        target_resolved = (not any(m["breaches_1h"] for m in repaired.values())
                           and repaired == baseline)
        regression["baseline_restored"] = repaired == baseline
        regression["preexisting_miss_preserved"] = (
            repaired.get("CHS-B", {}).get("classification")
            == "confirmed-miss")
        regression["no_new_anomaly"] = not any(
            m["ordering_anomaly"] for m in repaired.values())
    else:
        target_resolved = not any(m["discrepancy"]
                                  for m in repaired.values())
        regression["source_unchanged"] = all(
            c in baseline and repaired[c]["source_ack"] == baseline[c]["source_ack"]
            for c in repaired)
        regression["no_unexpected_records"] = (
            set(repaired) == set(baseline))
        regression["feed_matches_source"] = all(
            repaired[c]["feed_ack"] == repaired[c]["source_ack"]
            for c in repaired)
    if target_resolved and all(regression.values()):
        status = "verified"
    elif not target_resolved or not all(regression.values()):
        status = "failed"
    else:  # unreachable by construction; kept for schema completeness
        status = "inconclusive"
    return {
        "schema": SCHEMA,
        "scenario_id": scenario_id,
        "repair_id": repair_id,
        "fixture_id": FIXTURE_ID,
        "fixture_digest": fixture_digest(),
        "baseline": baseline,
        "fault_observations": faulted,
        "pre_repair_flags": sorted(
            c for c, m in faulted.items()
            if m.get("breaches_1h") or m.get("discrepancy")
            or m.get("classification") == "incomplete"),
        "repair": {"description": ALLOWLIST[(scenario_id, repair_id)],
                   "changes": list(changes)},
        "post_repair": repaired,
        "post_repair_flags": sorted(
            c for c, m in repaired.items()
            if m.get("breaches_1h") or m.get("discrepancy")
            or m.get("classification") == "incomplete"),
        "target_resolved": target_resolved,
        "regression": regression,
        "status": status,
        "note": note,
        "refs": [f"{FIXTURE_ID}/assign.csv",
                 f"{FIXTURE_ID}/ack_source.csv",
                 f"{FIXTURE_ID}/ack_feed.csv"],
    }


def _finalize(result: dict) -> dict:
    run_id = _sha256(b"\x00".join([
        result["scenario_id"].encode(), result["repair_id"].encode(),
        result["fixture_digest"].encode(),
        _canonical(result["baseline"]), _canonical(result["fault_observations"]),
        _canonical(result.get("post_repair")),
        result["status"].encode()]))
    result["run_id"] = run_id
    return result


def run_recovery_test(scenario_id: str, repair_id: str) -> dict:
    """Execute one allowlisted repair-and-retest on isolated copies."""
    if scenario_id == "CHS-WINDOW-01":
        return _finalize({
            "schema": SCHEMA, "scenario_id": scenario_id,
            "repair_id": repair_id, "fixture_id": FIXTURE_ID,
            "fixture_digest": fixture_digest(),
            "baseline": {}, "fault_observations": {},
            "pre_repair_flags": [],
            "repair": {"description": "no allowlisted repair",
                       "changes": []},
            "post_repair": None, "post_repair_flags": [],
            "target_resolved": False, "regression": {},
            "status": "not-tested",
            "note": "Recovery not tested — insufficient verified "
                    "post-repair evidence. Extending the window would need "
                    "new synthetic source records showing an acknowledgment "
                    "arriving inside the extended interval; none exist, and "
                    "missing timestamps must not be manufactured.",
            "refs": [f"{FIXTURE_ID}/window.csv"],
        })
    if (scenario_id, repair_id) not in ALLOWLIST:
        raise ChaosRecoveryError(
            f"unknown scenario/repair pairing: {scenario_id}/{repair_id}",
            "unknown-pairing")
    if scenario_id == "CHS-ASSIGN-01":
        rows = _read_csv("assign.csv")
        baseline = measure_assign(rows)
        faulted_rows = []
        for row in rows:
            copy = dict(row)
            if copy.get("assigned_at", "").strip():
                shifted = _parse_ts(copy["assigned_at"]) + timedelta(
                    minutes=SHIFT_MINUTES)
                copy["assigned_at"] = shifted.isoformat()
            faulted_rows.append(copy)
        faulted = measure_assign(faulted_rows)
        repaired_data, changes = apply_repair(
            scenario_id, repair_id, {"rows": faulted_rows})
        repaired = measure_assign(repaired_data["rows"])
        fault = "assignment timestamps shifted +300 minutes"
    else:
        source = {r["case_id"]: r["ack_at"] for r in _read_csv("ack_source.csv")}
        feed = {r["case_id"]: r["ack_at"] for r in _read_csv("ack_feed.csv")}
        baseline = measure_feed(source, dict(feed))
        faulted_feed = dict(feed)
        faulted_feed.pop("CHS-A", None)
        faulted = measure_feed(source, faulted_feed)
        repaired_data, changes = apply_repair(
            scenario_id, repair_id,
            {"source": source, "feed": faulted_feed})
        if repaired_data["source"] != source:
            raise ChaosRecoveryError("repair modified source records",
                                     "source-modified")
        repaired = measure_feed(repaired_data["source"],
                                repaired_data["feed"])
        fault = "CHS-A acknowledgment dropped from the feed copy"
    return _finalize(evaluate_repair(
        scenario_id, repair_id, fault, baseline, faulted, repaired, changes))


def list_recovery_scenarios() -> list[dict[str, str]]:
    return [
        {"scenario_id": "CHS-ASSIGN-01", "repair_id": "restore-assignments",
         "repair": ALLOWLIST[("CHS-ASSIGN-01", "restore-assignments")]},
        {"scenario_id": "CHS-ACK-01", "repair_id": "reconcile-feed",
         "repair": ALLOWLIST[("CHS-ACK-01", "reconcile-feed")]},
        {"scenario_id": "CHS-WINDOW-01", "repair_id": "none-available",
         "repair": "No allowlisted repair; yields not-tested."},
    ]


def validate_recovery_result(result: dict) -> dict[str, str]:
    """Strictly validate a recovery result; raises ChaosRecoveryError."""
    checks: dict[str, str] = {}

    def need(cond: bool, code: str) -> None:
        if not cond:
            raise ChaosRecoveryError(f"invalid recovery result: {code}", code)

    need(isinstance(result, dict), "malformed")
    need(result.get("schema") == SCHEMA, "bad-schema")
    need(isinstance(result.get("scenario_id"), str), "malformed")
    need(result.get("fixture_digest") == fixture_digest(),
         "fixture-mismatch")
    checks["fixture"] = "pinned"
    need(result.get("status") in ("verified", "failed", "inconclusive",
                                  "not-tested"), "bad-status")
    if result["status"] == "not-tested":
        need(result.get("post_repair") is None, "malformed")
        need(bool(result.get("note")), "malformed")
    else:
        need(isinstance(result.get("post_repair"), dict)
             and result["post_repair"], "malformed")
        need(isinstance(result.get("target_resolved"), bool), "malformed")
        need(isinstance(result.get("regression"), dict)
             and result["regression"], "malformed")
        if result["status"] == "verified":
            need(result["target_resolved"]
                 and all(result["regression"].values()), "unverified-claim")
        if result["status"] == "failed":
            need(not result["target_resolved"]
                 or not all(result["regression"].values()), "malformed")
    checks["status"] = "consistent"
    for key in ("baseline", "fault_observations"):
        need(isinstance(result.get(key), dict), "malformed")
    need(isinstance(result.get("repair"), dict)
         and isinstance(result["repair"].get("changes"), list), "malformed")
    need(isinstance(result.get("refs"), list) and result["refs"]
         and all(isinstance(r, str) for r in result["refs"]), "malformed")
    for banned in ("confidence", "executed", "production"):
        need(banned not in json.dumps(result).lower(), "fabricated-field")
    expected_run = _sha256(b"\x00".join([
        result["scenario_id"].encode(), result["repair_id"].encode(),
        result["fixture_digest"].encode(),
        _canonical(result["baseline"]),
        _canonical(result["fault_observations"]),
        _canonical(result.get("post_repair")), result["status"].encode()]))
    need(result.get("run_id") == expected_run, "run-mismatch")
    checks["run"] = "reproducible"
    checks["schema"] = "valid"
    return checks
