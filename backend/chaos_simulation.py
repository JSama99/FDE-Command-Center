"""Deterministic offline chaos simulations (MC-005b).

Isolated, synthetic-only fault-injection experiments over dedicated
fixtures in fixtures/chaos-lab/. Standard library only; no network, no
subprocesses, no credentials, no model calls, no writes anywhere.

Boundaries, enforced by design and tests:
- Fixtures are read, never written; case-001 evidence is never loaded.
- No mission, experiment, receipt, or snapshot state is touched: these
  functions take no context objects.
- Nothing here knows the Field Mission EXP-001 outcome; the ack-feed
  fixture is independently authored.
- Detector output is checked against controlled injected truth, and
  agreement is reported as accuracy — never as independent discovery.
- Recovery is always "not-tested": no recovery test exists yet.

Thresholds mirror the fictional case-001 policy rules (60-minute
assignment, 240-minute acknowledgment, complete-window requirement)
so simulated detections use the same yardstick as the evidence
ledger; they are constants of the fictional scenario, not findings.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = "ChaosSimulationResultV1"
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "chaos-lab"
ASSIGN_LIMIT_MIN = 60
ACK_LIMIT_MIN = 240
VARIANTS = ("baseline", "injected")

SCENARIOS = {
    "CHS-ASSIGN-01": {
        "title": "Assignment delay",
        "fault": "Assignment timestamps shifted +300 minutes on the in-memory copy.",
        "fixtures": ("assign.csv",),
    },
    "CHS-ACK-01": {
        "title": "Acknowledgment feed gap",
        "fault": "CHS-A acknowledgment dropped from the in-memory feed copy.",
        "fixtures": ("ack_source.csv", "ack_feed.csv"),
    },
    "CHS-WINDOW-01": {
        "title": "Incomplete observation window",
        "fault": "CHS-W2 window_close moved to 09:00 on the in-memory copy.",
        "fixtures": ("window.csv",),
    },
}


class ChaosError(ValueError):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def list_scenarios() -> list[dict[str, str]]:
    return [{"scenario_id": sid, "title": spec["title"],
             "fault": spec["fault"], "fixtures": list(spec["fixtures"])}
            for sid, spec in SCENARIOS.items()]


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fixture_bytes() -> dict[str, bytes]:
    out = {}
    for name in sorted(p.name for p in FIXTURE_DIR.iterdir() if p.is_file()):
        out[name] = (FIXTURE_DIR / name).read_bytes()
    return out


def _parse_ts(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    return datetime.fromisoformat(raw)


def _minutes(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return (a - b).total_seconds() / 60


def _load_rows(name: str) -> list[dict[str, str]]:
    with open(FIXTURE_DIR / name, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _measure_assign(rows: list[dict[str, str]]) -> dict[str, dict]:
    measured = {}
    for row in rows:
        created = _parse_ts(row["created_at"])
        assigned = _parse_ts(row.get("assigned_at", ""))
        ack = _parse_ts(row.get("ack_at", ""))
        close = _parse_ts(row["window_close_at"])
        delay = _minutes(assigned, created)
        window_complete = (close is not None and created is not None
                           and (close - created).total_seconds() / 60 >= ACK_LIMIT_MIN)
        anomaly = ((assigned is not None and created is not None and assigned < created)
                   or (ack is not None and created is not None and ack < created)
                   or (ack is not None and assigned is not None and ack < assigned))
        ack_valid = (ack is not None and created is not None
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
            "ordering_anomaly": anomaly,
            "ack_valid": ack_valid,
            "classification": classification,
        }
    return measured


def _run_assign(variant: str) -> tuple[dict, dict, dict]:
    rows = _load_rows("assign.csv")
    baseline = _measure_assign(rows)
    injected_rows = [dict(r) for r in rows]
    fault = "none (baseline variant)"
    if variant == "injected":
        fault = SCENARIOS["CHS-ASSIGN-01"]["fault"]
        for r in injected_rows:
            if r.get("assigned_at", "").strip():
                shifted = _parse_ts(r["assigned_at"])
                if shifted is not None:
                    r["assigned_at"] = (shifted + timedelta(minutes=300)).isoformat()
    observed = _measure_assign(injected_rows)
    flagged = sorted(c for c, m in observed.items() if m["breaches_1h"])
    detector = {
        "name": "assignment-delay-1h",
        "rule": "flag cases with assigned_at - created_at > 60 minutes",
        "flagged": flagged,
        "basis": flagged,
    }
    return baseline, observed, detector


def _run_ack(variant: str) -> tuple[dict, dict, dict]:
    source = {r["case_id"]: r["ack_at"] for r in _load_rows("ack_source.csv")}
    feed = {r["case_id"]: r["ack_at"] for r in _load_rows("ack_feed.csv")}
    baseline_feed = dict(feed)
    fault = "none (baseline variant)"
    if variant == "injected":
        fault = SCENARIOS["CHS-ACK-01"]["fault"]
        feed.pop("CHS-A", None)
    observed = {case: {"source_ack": source.get(case),
                       "feed_ack": feed.get(case),
                       "discrepancy": source.get(case) != feed.get(case)}
                for case in sorted(set(source) | set(feed) | set(baseline_feed))}
    flagged = sorted(c for c, m in observed.items() if m["discrepancy"])
    detector = {
        "name": "feed-source-reconciliation",
        "rule": "flag cases where source and feed acknowledgments differ",
        "flagged": flagged,
        "basis": flagged,
    }
    baseline = {case: {"source_ack": source.get(case),
                       "feed_ack": baseline_feed.get(case),
                       "discrepancy": source.get(case) != baseline_feed.get(case)}
                for case in sorted(set(source) | set(baseline_feed))}
    return baseline, observed, detector


def _run_window(variant: str) -> tuple[dict, dict, dict]:
    rows = _load_rows("window.csv")
    fault = "none (baseline variant)"
    if variant == "injected":
        fault = SCENARIOS["CHS-WINDOW-01"]["fault"]
        rows = [dict(r, window_close_at="2026-09-10T09:00:00")
                if r["case_id"] == "CHS-W2" else dict(r) for r in rows]
    measured = _measure_assign(rows)
    baseline = _measure_assign(_load_rows("window.csv"))
    flagged = sorted(c for c, m in measured.items() if not m["window_complete"])
    detector = {
        "name": "window-observability",
        "rule": "flag cases whose window closes before created_at + 240 minutes; "
                "flagged cases are incomplete, never confirmed misses",
        "flagged": flagged,
        "basis": flagged,
    }
    return baseline, measured, detector


_RUNNERS = {"CHS-ASSIGN-01": _run_assign, "CHS-ACK-01": _run_ack,
            "CHS-WINDOW-01": _run_window}

# Each flagged case must satisfy its detector's rule on the recorded
# observation: (observation key, required value).
_SUPPORT_RULES = {
    "assignment-delay-1h": ("breaches_1h", True),
    "feed-source-reconciliation": ("discrepancy", True),
    "window-observability": ("window_complete", False),
}

# Specified flag sets per scenario and variant, derived from the rules
# above applied to the fixed fixtures.
_EXPECTED_FLAGS = {
    ("CHS-ASSIGN-01", "baseline"): [],
    ("CHS-ASSIGN-01", "injected"): ["CHS-A", "CHS-B", "CHS-C"],
    ("CHS-ACK-01", "baseline"): [],
    ("CHS-ACK-01", "injected"): ["CHS-A"],
    ("CHS-WINDOW-01", "baseline"): ["CHS-W1"],
    ("CHS-WINDOW-01", "injected"): ["CHS-W1", "CHS-W2"],
}


def run_simulation(scenario_id: str,
                   variant: str = "injected") -> dict:
    """Execute one deterministic simulation; returns ChaosSimulationResultV1."""
    if scenario_id not in SCENARIOS:
        raise ChaosError(f"unknown scenario: {scenario_id}",
                         "unknown-scenario")
    if variant not in VARIANTS:
        raise ChaosError(f"unknown variant: {variant}", "unknown-variant")
    spec = SCENARIOS[scenario_id]
    blobs = fixture_bytes()
    fixture_digest = _sha256(b"".join(blobs[name] for name in spec["fixtures"]))
    baseline, observed, detector = _RUNNERS[scenario_id](variant)
    injected_truth = {"variant": variant,
                      "fault": spec["fault"] if variant == "injected"
                      else "none (baseline variant)"}
    # Specified detector behavior on the fixed fixtures: the flag sets
    # below follow directly from the detector rules in _SUPPORT_RULES.
    # They document what the detector must report, not a hidden answer.
    expected = _EXPECTED_FLAGS[(scenario_id, variant)]
    agreement = detector["flagged"] == expected
    result = {
        "schema": SCHEMA,
        "scenario_id": scenario_id,
        "variant": variant,
        "synthetic_fixture_id": "fixtures/chaos-lab",
        "fixture_digest": fixture_digest,
        "baseline": baseline,
        "injected_fault": injected_truth,
        "observations": observed,
        "detector": detector,
        "expected_vs_observed": {
            "injected_truth": injected_truth,
            "detector_output": detector["flagged"],
            "agreement": agreement,
            "note": "Agreement measures detector accuracy against controlled "
                    "truth; it is not independent discovery of a fault.",
        },
        "refs": sorted({f"fixtures/chaos-lab/{n}" for n in spec["fixtures"]}),
        "classification": "synthetic simulation",
        "status": "completed",
        "recovery": "not-tested",
    }
    run_id = _sha256(b"\x00".join([
        scenario_id.encode(), variant.encode(),
        fixture_digest.encode(), _canonical(observed)]))
    result["run_id"] = run_id
    return result


def validate_simulation_result(result: dict) -> dict[str, str]:
    """Strictly validate a simulation result; raises ChaosError."""
    checks: dict[str, str] = {}

    def need(cond: bool, code: str) -> None:
        if not cond:
            raise ChaosError(f"invalid simulation result: {code}", code)

    need(isinstance(result, dict), "malformed")
    need(result.get("schema") == SCHEMA, "bad-schema")
    need(result.get("scenario_id") in SCENARIOS, "unknown-scenario")
    need(result.get("variant") in VARIANTS, "unknown-variant")
    need(result.get("classification") == "synthetic simulation",
         "bad-classification")
    need(result.get("status") == "completed", "bad-status")
    need(result.get("recovery") == "not-tested", "recovery-unverified")
    spec = SCENARIOS[result["scenario_id"]]
    blobs = fixture_bytes()
    expected_digest = _sha256(b"".join(blobs[n] for n in spec["fixtures"]))
    need(result.get("fixture_digest") == expected_digest,
         "fixture-mismatch")
    checks["fixture"] = "pinned"
    need(isinstance(result.get("observations"), dict)
         and result["observations"], "malformed")
    detector = result.get("detector")
    need(isinstance(detector, dict)
         and isinstance(detector.get("flagged"), list)
         and isinstance(detector.get("basis"), list)
         and detector.get("rule"), "malformed")
    observed = result["observations"]
    need(all(c in observed for c in detector["flagged"]),
         "unsupported-flag")
    need(all(c in observed for c in detector["basis"]),
         "unsupported-flag")
    rule = _SUPPORT_RULES.get(detector.get("name"))
    need(rule is not None, "unknown-detector")
    key, want = rule
    need(all(observed[c].get(key) is want for c in detector["flagged"]),
         "unsupported-flag")
    checks["detector"] = "grounded"
    expected_run = _sha256(b"\x00".join([
        result["scenario_id"].encode(), result["variant"].encode(),
        expected_digest.encode(), _canonical(observed)]))
    need(result.get("run_id") == expected_run, "run-mismatch")
    checks["run"] = "reproducible"
    need(isinstance(result.get("refs"), list) and result["refs"]
         and all(isinstance(r, str) for r in result["refs"]), "malformed")
    for banned in ("confidence", "executed", "production"):
        need(banned not in json.dumps(result).lower(), "fabricated-field")
    checks["schema"] = "valid"
    return checks
