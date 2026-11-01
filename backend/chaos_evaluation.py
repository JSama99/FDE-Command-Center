"""Independent offline evaluation of chaos detectors (MC-005e).

Semantic discipline (these are not interchangeable):
- Detector alert: a case id appearing in `detector.flagged` — a
  rule firing on recorded observations, never a diagnosis.
- Policy classification: the per-case yardstick label
  (`confirmed-miss`, `incomplete`, `anomalous-needs-source-check`,
  `acknowledged`) — separate from whether any detector flagged it.
- Injected fault: controlled truth known to this oracle. Agreement
  between flags and truth measures detector accuracy; it is never
  counted as independent discovery of a fault.

Expected values below are hand-specified literals derived from the
fixture records and the documented detector rules — never copied from
detector outputs at runtime. Standard library only; no network, no
model calls, no writes, no state mutation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .chaos_simulation import (ChaosError, fixture_bytes, run_simulation,
                               validate_simulation_result)

SCHEMA = "ChaosEvaluationReportV1"
ENGINE_SCHEMA = "ChaosSimulationResultV1"
FIXTURE_ID = "fixtures/chaos-lab"

# Independent oracle: (scenario, variant) -> expectations.
# alert_expected: whether the detector should flag anything.
# expected_flags: the exact flag set the rules require on these fixtures.
# expected_classes: per-case policy classifications the yardstick requires.
ORACLE = {
    ("CHS-ASSIGN-01", "injected"): {
        # +300 minutes moves CHS-A's assignment (13:20) past its recorded
        # 10:00 acknowledgment, so the yardstick must report an ordering
        # anomaly for CHS-A — never a clean acknowledgment.
        "kind": "binary", "alert_expected": True,
        "expected_flags": ["CHS-A", "CHS-B", "CHS-C"],
        "expected_classes": {"CHS-A": "anomalous-needs-source-check",
                             "CHS-B": "confirmed-miss",
                             "CHS-C": "incomplete"},
        "rule": "R-ASSIGN-FLAG",
    },
    ("CHS-ASSIGN-01", "baseline"): {
        "kind": "binary", "alert_expected": False, "expected_flags": [],
        "expected_classes": {"CHS-A": "acknowledged",
                             "CHS-B": "confirmed-miss",
                             "CHS-C": "incomplete"},
        "rule": "R-ASSIGN-QUIET",
    },
    ("CHS-ACK-01", "injected"): {
        "kind": "binary", "alert_expected": True,
        "expected_flags": ["CHS-A"], "expected_classes": {},
        "rule": "R-ACK-FLAG",
    },
    ("CHS-ACK-01", "baseline"): {
        "kind": "binary", "alert_expected": False, "expected_flags": [],
        "expected_classes": {}, "rule": "R-ACK-QUIET",
    },
    ("CHS-WINDOW-01", "injected"): {
        "kind": "safety", "alert_expected": True,
        "expected_flags": ["CHS-W1", "CHS-W2"],
        "expected_classes": {"CHS-W1": "incomplete",
                             "CHS-W2": "incomplete"},
        "rule": "R-WINDOW-INCOMPLETE",
    },
    ("CHS-WINDOW-01", "baseline"): {
        "kind": "safety", "alert_expected": False,
        "expected_flags": ["CHS-W1"],
        "expected_classes": {"CHS-W1": "incomplete",
                             "CHS-W2": "confirmed-miss"},
        "rule": "R-WINDOW-OBSERVABLE",
    },
}

# Attribution case: CHS-B's confirmed miss preexists in the baseline and
# is not caused by the assignment-delay injection.
ATTRIBUTION = {
    "case": "C3-preexisting-violation",
    "scenario_id": "CHS-ASSIGN-01",
    "description": "CHS-B confirmed-miss present with and without injection",
    "rule": "R-PREEXISTING",
}

# Robustness cases: the validator (not a detector) must reject these.
ROBUSTNESS = [
    {"case": "C9-malformed-record", "rule": "R-REJECT-MALFORMED",
     "description": "schema-incompatible result rejected"},
    {"case": "C10-fabricated-flag", "rule": "R-REJECT-FABRICATED",
     "description": "detector flag without observation support rejected"},
]

UNAVAILABLE = [
    {"case": "C8-order-anomaly",
     "reason": "no chaos-lab fixture contains an ordering anomaly"},
]


def compute_metrics(tp: int, fp: int, tn: int, fn: int) -> dict[str, float | None]:
    """Binary metrics with explicit denominators; zero denominators
    yield None (undefined), never zero."""

    def ratio(num: int, den: int) -> float | None:
        return num / den if den else None

    return {
        "true_positives": tp, "false_positives": fp,
        "true_negatives": tn, "false_negatives": fn,
        "precision": ratio(tp, tp + fp),
        "precision_denominator": tp + fp,
        "recall": ratio(tp, tp + fn),
        "recall_denominator": tp + fn,
        "false_positive_rate": ratio(fp, fp + tn),
        "false_positive_rate_denominator": fp + tn,
        "false_negative_rate": ratio(fn, fn + tn),
        "false_negative_rate_denominator": fn + tn,
    }


def _refs(scenario_id: str) -> list[str]:
    from .chaos_simulation import SCENARIOS

    return sorted(f"fixtures/chaos-lab/{n}"
                  for n in SCENARIOS[scenario_id]["fixtures"])


def evaluate_case(scenario_id: str, variant: str) -> dict:
    """Run one oracle case independently of detector internals."""
    if (scenario_id, variant) not in ORACLE:
        return {"case": f"{scenario_id}.{variant}", "status": "error",
                "detail": "no oracle expectation defined"}
    want = ORACLE[(scenario_id, variant)]
    blobs = fixture_bytes()
    digest = hashlib.sha256(b"".join(sorted(blobs.values()))).hexdigest()
    try:
        result = run_simulation(scenario_id, variant)
        validate_simulation_result(result)
    except ChaosError as exc:
        return {"case": f"{scenario_id}.{variant}", "status": "error",
                "detail": exc.code, "rule": want["rule"],
                "refs": _refs(scenario_id)}
    observed_flags = list(result["detector"]["flagged"])
    observed_classes = {c: m.get("classification")
                        for c, m in result["observations"].items()}
    flags_ok = observed_flags == want["expected_flags"]
    classes_ok = all(observed_classes.get(c) == v
                     for c, v in want["expected_classes"].items())
    passed = flags_ok and classes_ok
    return {
        "case": f"{scenario_id}.{variant}", "kind": want["kind"],
        "rule": want["rule"], "status": "pass" if passed else "fail",
        "scenario_id": scenario_id, "variant": variant,
        "fixture_id": FIXTURE_ID, "fixture_digest": digest,
        "injected_truth": result["injected_fault"],
        "observed_flags": observed_flags,
        "expected_flags": want["expected_flags"],
        "observed_classes": observed_classes,
        "expected_classes": want["expected_classes"],
        "refs": _refs(scenario_id) + sorted(result["refs"]),
    }


def evaluate_attribution() -> dict:
    """C3: the CHS-B miss must be visible in both variants (preexisting)."""
    base = run_simulation("CHS-ASSIGN-01", "baseline")
    injected = run_simulation("CHS-ASSIGN-01", "injected")
    preexists = (base["observations"]["CHS-B"]["classification"]
                 == injected["observations"]["CHS-B"]["classification"]
                 == "confirmed-miss")
    return {
        "case": ATTRIBUTION["case"], "rule": ATTRIBUTION["rule"],
        "status": "pass" if preexists else "fail",
        "scenario_id": "CHS-ASSIGN-01",
        "detail": "CHS-B confirmed-miss in baseline and injected"
                  if preexists else "miss classification changed",
        "refs": _refs("CHS-ASSIGN-01"),
    }


def evaluate_robustness() -> list[dict]:
    """C9/C10: malformed and fabricated results must be rejected."""
    import copy

    outcomes = []
    good = run_simulation("CHS-ACK-01", "injected")
    malformed = dict(good, schema="ChaosResultV9")
    try:
        validate_simulation_result(malformed)
        outcomes.append({"case": "C9-malformed-record",
                         "rule": "R-REJECT-MALFORMED", "status": "fail",
                         "refs": _refs("CHS-ACK-01")})
    except ChaosError:
        outcomes.append({"case": "C9-malformed-record",
                         "rule": "R-REJECT-MALFORMED", "status": "pass",
                         "refs": _refs("CHS-ACK-01")})
    fabricated = copy.deepcopy(good)
    fabricated["detector"] = dict(good["detector"], flagged=["CHS-B"],
                                  basis=["CHS-B"])
    try:
        validate_simulation_result(fabricated)
        outcomes.append({"case": "C10-fabricated-flag",
                         "rule": "R-REJECT-FABRICATED", "status": "fail",
                         "refs": _refs("CHS-ACK-01")})
    except ChaosError:
        outcomes.append({"case": "C10-fabricated-flag",
                         "rule": "R-REJECT-FABRICATED", "status": "pass",
                         "refs": _refs("CHS-ACK-01")})
    return outcomes


def evaluate() -> dict:
    """Full offline evaluation; deterministic from fixed inputs."""
    run_cases = [evaluate_case(sid, variant)
                 for (sid, variant) in sorted(ORACLE)]
    binary = [j for j in run_cases if j.get("kind") == "binary"]
    tp = sum(1 for j in binary
             if j["status"] == "pass" and j["observed_flags"])
    tn = sum(1 for j in binary
             if j["status"] == "pass" and not j["observed_flags"])
    fp = sum(1 for j in binary
             if j["status"] == "fail" and j.get("observed_flags"))
    fn = sum(1 for j in binary
             if j["status"] == "fail" and not j.get("observed_flags", True))
    safety = [j for j in run_cases if j.get("kind") == "safety"]
    safety_ok = sum(1 for j in safety if j["status"] == "pass")
    attribution = evaluate_attribution()
    robustness = evaluate_robustness()
    failures = [j["case"] for j in run_cases + [attribution] + robustness
                if j["status"] != "pass"]
    blobs = fixture_bytes()
    digest = hashlib.sha256(b"".join(sorted(blobs.values()))).hexdigest()
    return {
        "schema": SCHEMA,
        "engine_schema": ENGINE_SCHEMA,
        "fixture_id": FIXTURE_ID,
        "fixture_digest": digest,
        "judgments": run_cases + [attribution] + robustness,
        "confusion": {"true_positives": tp, "false_positives": fp,
                      "true_negatives": tn, "false_negatives": fn},
        "metrics": compute_metrics(tp, fp, tn, fn),
        "safety": {"cases": len(safety), "correct": safety_ok},
        "attribution": attribution["status"],
        "robustness": {j["case"]: j["status"] for j in robustness},
        "indeterminate": 0,
        "unavailable": UNAVAILABLE,
        "overall": "pass" if not failures else "fail",
        "failures": failures,
        "scope": "synthetic offline evaluation only; passing here does "
                 "not establish production reliability",
    }
