"""Locked-prediction experiment EXP-001 (Task 006). Synthetic only.

Discriminating question: are the case-001 failures driven by queue handling
that leaves urgent cases unassigned (H-QUEUE), or by a separate
acknowledgment workflow bottleneck or reporting problem (H-ACK)?

Test procedure: re-examine the source log for case-003 (assigned 09:10, no
acknowledgment in the events feed, complete observation window) and record
whether an acknowledgment exists there that never reached the feed.

Outcome independence: the outcome below was authored once, fixed at
implementation time, before any prediction was locked. No prediction exists
yet, so the outcome cannot have been selected to flatter one. The user-locked
prediction is compared against it by deterministic application logic.

Secrecy scope: the outcome lives server-side only. It is excluded from model
context, the inspection report, mock/live investigations, and every static
file served to the browser. It is disclosed only by the authorized reveal
action after a valid prediction lock.

Hash note: the locked prediction's SHA-256 is recorded as a change-detection
aid for demo logs. It is not described as tamperproof and is not a security
boundary.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

EXPERIMENT_ID = "EXP-001"
PREDICTION_VERSION = "v1"

HYPOTHESES = {
    "H-QUEUE": "Assignment delays caused by queue handling leave urgent cases unassigned or late.",
    "H-ACK": "A separate acknowledgment workflow bottleneck or reporting problem loses timely acknowledgments.",
}

EXPECTED_FINDINGS = ("ack-found", "no-ack")

PROCEDURE = (
    "Re-examine the source log for case-003 (assigned 09:10, no acknowledgment "
    "in the events feed, complete observation window) and record whether an "
    "acknowledgment exists there that never reached the feed."
)

CRITERIA_INFO = (
    'Predict "ack-found" if you expect the source log to hold a case-003 '
    'acknowledgment missing from the feed (supports H-ACK); predict "no-ack" '
    "if you expect no such entry (supports H-QUEUE for the assigned class)."
)

# Fixed at implementation time. Never served before authorized reveal.
OUTCOME = {
    "finding": "ack-found",
    "detail": (
        "Source-log check for case-003 finds a recorded acknowledgment at 09:40 "
        "that never reached the events feed (feed token SRC-FEED-GAP-09:40)."
    ),
    "refs": ["case-003", "events.csv"],
}

OUTCOME_MARKERS = ("SRC-FEED-GAP-09:40",)


class ExperimentError(ValueError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


def new_experiment_state() -> dict:
    return {
        "status": "proposed",
        "prediction": None,
        "outcome": None,
        "assessment": None,
        "revision": None,
        "revision_validation": None,
    }


def public_definition() -> dict:
    return {
        "experiment_id": EXPERIMENT_ID,
        "title": "Source-log check for case-003",
        "question": "Queue-handling assignment delays, or a separate acknowledgment bottleneck?",
        "hypotheses": [{"id": hid, "text": text} for hid, text in HYPOTHESES.items()],
        "procedure": PROCEDURE,
        "criteria_info": CRITERIA_INFO,
        "expected_findings": list(EXPECTED_FINDINGS),
    }


def public_view(state: dict) -> dict:
    view: dict = {"definition": public_definition(), "status": state["status"]}
    if state["prediction"] is not None:
        view["prediction"] = state["prediction"]
    if state["outcome"] is not None:
        view["outcome"] = state["outcome"]
    if state["assessment"] is not None:
        view["assessment"] = state["assessment"]
    if state["revision"] is not None:
        view["revision"] = state["revision"]
    if state["revision_validation"] is not None:
        view["revision_validation"] = state["revision_validation"]
    return view


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def lock_prediction(
    state: dict,
    payload: object,
    registry: dict,
    now: int,
    origin: str = "human-authored",
    extra: dict | None = None,
) -> dict:
    if state["status"] != "proposed" or state["prediction"] is not None:
        raise ExperimentError("prediction is already locked and cannot be changed", "already-locked")
    if origin not in ("human-authored", "ai-generated"):
        raise ExperimentError("unknown prediction origin", "bad-prediction")
    if not isinstance(payload, dict):
        raise ExperimentError("prediction must be an object", "bad-prediction")
    hypothesis_id = payload.get("hypothesis_id")
    expected = payload.get("expected_finding")
    observation = payload.get("expected_observation")
    criteria = payload.get("criteria")
    refs = payload.get("refs")
    if hypothesis_id not in HYPOTHESES:
        raise ExperimentError("unknown hypothesis id", "bad-prediction")
    if expected not in EXPECTED_FINDINGS:
        raise ExperimentError("expected_finding must be one of ack-found, no-ack", "bad-prediction")
    if not isinstance(observation, str) or not observation.strip():
        raise ExperimentError("expected_observation must be a non-empty string", "bad-prediction")
    if not isinstance(criteria, str) or not criteria.strip():
        raise ExperimentError("criteria must be a non-empty string", "bad-prediction")
    if not isinstance(refs, list) or not refs or not all(isinstance(r, str) and r for r in refs):
        raise ExperimentError("refs must be a non-empty list", "bad-prediction")
    for ref in refs:
        if ref not in registry["docs"] and ref not in registry["cases"]:
            raise ExperimentError(f"unknown evidence reference: {ref!r}", "bad-reference")
    # Fidelity rule: the locked record preserves the reviewed prediction
    # verbatim. No trimming, no dropped fields. Optional full-prediction
    # fields pass through untouched when the caller reviewed them.
    record = {
        "experiment_id": EXPERIMENT_ID,
        "version": PREDICTION_VERSION,
        "origin": origin,
        "hypothesis_id": hypothesis_id,
        "expected_finding": expected,
        "expected_observation": observation,
        "criteria": criteria,
        "refs": list(refs),
        "locked_at": now,
    }
    for key in ("test_procedure", "uncertainty", "alternatives", "metrics"):
        if key in payload:
            value = payload[key]
            if key in ("test_procedure", "uncertainty"):
                if not isinstance(value, str) or not value:
                    raise ExperimentError(f"{key} must be preserved verbatim", "bad-prediction")
            if key == "alternatives":
                if not isinstance(value, list) or not value:
                    raise ExperimentError("alternatives must be preserved verbatim", "bad-prediction")
                for alt in value:
                    if not isinstance(alt, dict) or not alt.get("text") or not alt.get("refs"):
                        raise ExperimentError("alternatives must be preserved verbatim", "bad-prediction")
                    for ref in alt["refs"]:
                        if ref not in registry["docs"] and ref not in registry["cases"]:
                            raise ExperimentError(f"unknown evidence reference: {ref!r}", "bad-reference")
            if key == "metrics" and not isinstance(value, dict):
                raise ExperimentError("metrics must be preserved verbatim", "bad-prediction")
            record[key] = copy.deepcopy(value)
    if extra:
        record.update(extra)
    record["hash"] = hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest()
    state["prediction"] = record
    state["status"] = "prediction locked"
    return record


def reveal_outcome(state: dict, now: int) -> dict:
    if state["status"] != "prediction locked" or state["prediction"] is None:
        raise ExperimentError("reveal requires a locked prediction", "too-early")
    outcome = {"experiment_id": EXPERIMENT_ID, "revealed_at": now, **OUTCOME}
    state["outcome"] = outcome
    state["status"] = "result revealed"
    return outcome


def assess(state: dict) -> dict:
    if state["status"] != "result revealed" or state["outcome"] is None or state["prediction"] is None:
        raise ExperimentError("assessment requires a revealed result", "too-early")
    prediction = state["prediction"]
    outcome = state["outcome"]
    match = prediction["expected_finding"] == outcome["finding"]
    refs = sorted(set(prediction["refs"]) | set(outcome["refs"]))
    if match:
        result, reason = "supported", (
            f"Predicted {prediction['expected_finding']} matches the revealed "
            f"{outcome['finding']} for {prediction['hypothesis_id']}."
        )
    else:
        result, reason = "contradicted", (
            f"Predicted {prediction['expected_finding']} but revealed "
            f"{outcome['finding']} for {prediction['hypothesis_id']}."
        )
    assessment = {"experiment_id": EXPERIMENT_ID, "result": result, "reason": reason, "refs": refs}
    state["assessment"] = assessment
    state["status"] = "assessed"
    return assessment


def build_registry(base_dir: str | Path):
    from .report import build_case_report

    from .investigation import build_evidence_registry

    return build_evidence_registry(build_case_report(base_dir))
