"""AI prediction, revision, and learning loop (Task 007). Synthetic only.

An AI-generated prediction is built strictly from pre-reveal evidence
(verified quotes, computed metrics, H-QUEUE/H-ACK, experiment procedure).
The withheld outcome, its markers, and prior results never enter prediction
context, instructions, initial responses, or static files. Because outcome
and code share this repository, AI predictions here demonstrate workflow,
not a genuine blind evaluation; the UI labels them accordingly.

After reveal, a revision references the locked prediction, the new evidence,
and the deterministic assessment. Originals are preserved; the revision is
stored as a new version. A matching prediction never becomes a verified root
cause: support and proof stay distinct, and model-declared root causes are
rejected.
"""

from __future__ import annotations

import json
from pathlib import Path

from .experiment import (
    EXPECTED_FINDINGS,
    HYPOTHESES,
    OUTCOME_MARKERS,
    PROCEDURE,
    assess as _assess,
)
from .investigation import (
    DOC_REFS,
    DiagnosticError,
    _check_metrics,
    _check_refs,
    _fail,
    build_evidence_registry,
)
from .meta_adapter import MODEL_ID, MalformedResponseError
from .report import build_case_report

AI_PREDICTION_VERSION = "v2"

FORBIDDEN_CONCLUSIONS = (
    "verified root cause",
    "proven root cause",
    "root cause proven",
    "root cause is proven",
    "root cause confirmed",
    "causal explanation validated",
    "causality proven",
)


def _no_leak(value: object, where: str) -> None:
    blob = json.dumps(value)
    for marker in OUTCOME_MARKERS:
        if marker in blob:
            raise DiagnosticError(
                f"withheld outcome leaked into {where}",
                stage="prediction-context",
                category="answer-leakage",
                field_path=where,
            )


def build_prediction_context(report: dict) -> dict:
    """Pre-reveal evidence only. Raises if a withheld marker is present."""
    context = {
        "case_id": report["case_id"],
        "policy_requirements": report["policy_requirements"],
        "dispatcher_statements": report["dispatcher_statements"],
        "manager_statements": report["manager_statements"],
        "calculations": report["calculations"],
        "hypotheses": [{"id": hid, "text": text} for hid, text in HYPOTHESES.items()],
        "experiment_question": "Queue-handling assignment delays, or a separate acknowledgment bottleneck?",
        "experiment_procedure": PROCEDURE,
    }
    _no_leak(context, "prediction-context")
    return context


def build_prediction_instructions(registry: dict) -> str:
    doc_refs = ", ".join(f'"{r}"' for r in sorted(DOC_REFS))
    case_refs = ", ".join(f'"{c}"' for c in sorted(registry["cases"]))
    metric_lines = "\n".join(
        f'- "{label}": {value}' for label, value in sorted(registry["metrics"].items())
    )
    findings = ", ".join(f'"{f}"' for f in EXPECTED_FINDINGS)
    hyps = ", ".join(f'"{h}"' for h in sorted(HYPOTHESES))
    return (
        "Return a single JSON object with exactly these keys: hypothesis_id, "
        "expected_finding, expected_observation, test_procedure, criteria, "
        "refs, uncertainty, alternatives, metrics (optional).\n"
        f"- hypothesis_id: one of {hyps}.\n"
        f"- expected_finding: one of {findings}.\n"
        "- expected_observation, test_procedure, criteria, uncertainty: non-empty strings.\n"
        "- refs: non-empty list using only these references. Documents: "
        f"{doc_refs}. Cases: {case_refs}.\n"
        "- alternatives: non-empty list of {\"text\": string, \"refs\": [ref...]}.\n"
        "- metrics (optional): only the labels below with exactly these values. "
        "Put numbers only here.\n"
        f"{metric_lines}\n"
        "You have not seen the experiment outcome. Do not guess hidden content; "
        "reason only from the evidence provided."
    )


def validate_prediction(payload: object, registry: dict) -> dict:
    if not isinstance(payload, dict):
        raise _fail("prediction must be a JSON object", category="malformed-item", field_path="")
    if payload.get("hypothesis_id") not in HYPOTHESES:
        raise _fail(
            "unknown hypothesis id", category="bad-hypothesis", field_path="hypothesis_id"
        )
    if payload.get("expected_finding") not in EXPECTED_FINDINGS:
        raise _fail(
            "expected_finding must be ack-found or no-ack",
            category="bad-finding",
            field_path="expected_finding",
        )
    for field in ("expected_observation", "test_procedure", "criteria", "uncertainty"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise _fail(
                f"{field} must be a non-empty string", category="missing-field", field_path=field
            )
    _check_refs(payload.get("refs"), registry, "refs")
    alternatives = payload.get("alternatives")
    if not isinstance(alternatives, list) or not alternatives:
        raise _fail(
            "alternatives must be a non-empty list", category="missing-field", field_path="alternatives"
        )
    for i, alt in enumerate(alternatives):
        base = f"alternatives[{i}]"
        if not isinstance(alt, dict) or not alt.get("text"):
            raise _fail("each alternative needs text and refs", category="malformed-item", field_path=base)
        _check_refs(alt.get("refs"), registry, f"{base}.refs")
    _check_metrics(payload, registry)
    _no_leak(payload, "prediction-output")
    return payload


def build_evidence_cutoff(report: dict) -> dict:
    cats = report["categories"]
    return {
        "source": "fixtures/case-001/events.csv",
        "eligible_urgent": len(cats["eligible"]),
        "confirmed_misses": len(cats["confirmed_miss"]),
        "anomalous": len(cats["anomalous"]),
        "incomplete": len(cats["incomplete"]),
    }


def mock_prediction_payload() -> dict:
    """Fixed demonstration payload for offline UI testing. Labeled demo-only."""
    return {
        "hypothesis_id": "H-ACK",
        "expected_finding": "ack-found",
        "expected_observation": "Demonstration: the source log holds a case-003 acknowledgment missing from the feed.",
        "test_procedure": PROCEDURE,
        "criteria": "ack-found supports H-ACK; no-ack supports H-QUEUE for the assigned class.",
        "refs": ["case-003", "events.csv"],
        "uncertainty": "Demonstration: window and feed coverage for late-day cases is untested.",
        "alternatives": [
            {"text": "Demonstration: no source-log entry exists; the ack path itself failed.", "refs": ["case-003"]},
        ],
        "metrics": {"Eligible urgent cases": 7},
    }


def generate_ai_prediction(adapter, base_dir: str | Path, now: int) -> dict:
    from .investigation import parse_model_text

    report = build_case_report(base_dir)
    registry = build_evidence_registry(report)
    context = build_prediction_context(report)
    raw = adapter.request_structured(context, build_prediction_instructions(registry))
    payload = parse_model_text(raw) if isinstance(raw, str) else raw
    validated = validate_prediction(payload, registry)
    return {
        "origin": "ai-generated",
        "model_id": MODEL_ID,
        "prediction_version": AI_PREDICTION_VERSION,
        "evidence_cutoff": build_evidence_cutoff(report),
        "generated_at": now,
        "demonstration_only": True,
        "prediction": validated,
    }


STANCES = ("supported", "contradicted", "unresolved")


def build_revision_instructions(registry: dict) -> str:
    doc_refs = ", ".join(f'"{r}"' for r in sorted(DOC_REFS))
    case_refs = ", ".join(f'"{c}"' for c in sorted(registry["cases"]))
    return (
        "Return a single JSON object with exactly these keys: original_prediction, "
        "deterministic_assessment, new_evidence, effect_on_h_ack, effect_on_h_queue, "
        "remaining_alternatives, unresolved_questions, next_test, "
        "updated_recommendation, reversal_evidence, metrics (optional).\n"
        '- original_prediction: {"hypothesis_id": one of "H-QUEUE", "H-ACK", '
        '"expected_finding": string, "expected_observation": string} restating '
        "the locked prediction.\n"
        '- deterministic_assessment: {"result": one of "supported", '
        '"contradicted", "unresolved"} restating the backend assessment.\n'
        '- new_evidence: non-empty list of {"text": string, "refs": [ref...]}; at '
        "least one item must cite the revealed case evidence.\n"
        '- effect_on_h_ack and effect_on_h_queue: each {"stance": one of '
        '"supported", "contradicted", "unresolved", "scope": one of '
        '"single-case", "population", "reason": string, "refs": [ref...]} '
        "explaining how the new evidence changes that hypothesis at the "
        "declared scope. Population scope needs events.csv plus at least two "
        "distinct cases; contradicting a hypothesis needs population scope — "
        "one case never disproves the wider hypothesis. A match is support "
        "for the predicted hypothesis, never a verified root cause and never "
        "an organization-wide root cause. Never declare one anywhere.\n"
        "- remaining_alternatives: non-empty list of {\"text\": string, "
        '"refs": [ref...]}.\n'
        "- unresolved_questions: non-empty list of strings.\n"
        '- next_test: {"text": string, "expected_observations": string, '
        '"refs": [ref...]} proposing the next discriminating test.\n'
        "- updated_recommendation (provisional): {\"text\": string, "
        '"refs": [ref...], "requires_human_approval": true, '
        '"executes_production_change": false}.\n'
        '- reversal_evidence: non-empty list of {"text": string, "refs": [ref...]} '
        "naming evidence that could reverse the revised decision.\n"
        f"Allowed references and nothing else. Documents: {doc_refs}. Cases: {case_refs}.\n"
        "Use only the evidence provided below."
    )


def _forbids_conclusion(text: object, field_path: str) -> None:
    lowered = str(text).lower()
    for phrase in FORBIDDEN_CONCLUSIONS:
        if phrase in lowered:
            raise _fail(
                f"model must not declare a verified root cause ({phrase!r})",
                category="forbidden-conclusion",
                field_path=field_path,
            )
    if str(text).strip().lower() == "validated conclusion":
        raise _fail(
            "model must not claim validated conclusion",
            category="forbidden-conclusion",
            field_path=field_path,
        )


SCOPES = ("single-case", "population")


def _check_effect(item: object, field_path: str, registry: dict) -> dict:
    if not isinstance(item, dict):
        raise _fail("effect needs stance, scope, reason, and refs", category="malformed-item", field_path=field_path)
    if item.get("stance") not in STANCES:
        raise _fail(
            "effect stance must be supported, contradicted, or unresolved",
            category="bad-stance",
            field_path=f"{field_path}.stance",
        )
    scope = item.get("scope")
    if scope not in SCOPES:
        raise _fail(
            'effect must declare scope "single-case" or "population"',
            category="missing-scope",
            field_path=f"{field_path}.scope",
        )
    if not isinstance(item.get("reason"), str) or not item["reason"].strip():
        raise _fail(
            "effect needs a non-empty reason", category="missing-field", field_path=f"{field_path}.reason"
        )
    refs = _check_refs(item.get("refs"), registry, f"{field_path}.refs")
    case_refs = {r for r in refs if r in registry["cases"]}
    if scope == "population" and ("events.csv" not in refs or len(case_refs) < 2):
        # A population-level finding must cite the event population plus at
        # least two distinct cases. One case never carries the population.
        raise _fail(
            "population scope needs events.csv plus at least two distinct case references",
            category="scope-mismatch",
            field_path=f"{field_path}.scope",
        )
    if item["stance"] == "contradicted" and scope != "population":
        # Disproving a hypothesis needs population evidence. A single case can
        # support a narrow finding but never disprove the wider hypothesis;
        # without broader evidence the honest stance is unresolved.
        raise _fail(
            "a single case cannot disprove a wider operational hypothesis",
            category="overgeneralization",
            field_path=f"{field_path}.stance",
        )
    _forbids_conclusion(json.dumps(item), field_path)
    return item


def validate_revision(payload: object, registry: dict, locked: dict, outcome: dict, assessment: dict) -> dict:
    if not isinstance(payload, dict):
        raise _fail("revision must be a JSON object", category="malformed-item", field_path="")
    orig = payload.get("original_prediction")
    if not isinstance(orig, dict):
        raise _fail(
            "original_prediction must be an object",
            category="malformed-item",
            field_path="original_prediction",
        )
    if orig.get("hypothesis_id") != locked["hypothesis_id"]:
        raise _fail(
            "original prediction must match the locked hypothesis",
            category="revision-mismatch",
            field_path="original_prediction.hypothesis_id",
        )
    if orig.get("expected_finding") != locked["expected_finding"]:
        raise _fail(
            "original prediction must match the locked expected finding",
            category="revision-mismatch",
            field_path="original_prediction.expected_finding",
        )
    if not isinstance(orig.get("expected_observation"), str) or not orig["expected_observation"].strip():
        raise _fail(
            "original prediction needs its expected observation",
            category="missing-field",
            field_path="original_prediction.expected_observation",
        )
    det = payload.get("deterministic_assessment")
    if not isinstance(det, dict) or det.get("result") != assessment["result"]:
        raise _fail(
            "deterministic assessment must restate the backend result",
            category="revision-mismatch",
            field_path="deterministic_assessment.result",
        )
    new_evidence = payload.get("new_evidence")
    if not isinstance(new_evidence, list) or not new_evidence:
        raise _fail(
            "new_evidence must be a non-empty list", category="missing-field", field_path="new_evidence"
        )
    outcome_refs = set(outcome.get("refs", []))
    cited_new = False
    for i, item in enumerate(new_evidence):
        base = f"new_evidence[{i}]"
        if not isinstance(item, dict) or not item.get("text"):
            raise _fail("each new-evidence item needs text and refs", category="malformed-item", field_path=base)
        refs = _check_refs(item.get("refs"), registry, f"{base}.refs")
        cited_new = cited_new or bool(outcome_refs & set(refs))
    if not cited_new:
        raise _fail(
            "revision must reference the newly revealed evidence",
            category="revision-mismatch",
            field_path="new_evidence",
        )
    effects = {}
    for hypothesis_id, field in (("H-ACK", "effect_on_h_ack"), ("H-QUEUE", "effect_on_h_queue")):
        effects[hypothesis_id] = _check_effect(payload.get(field), field, registry)
    predicted_effect = effects[locked["hypothesis_id"]]
    if assessment["result"] == "supported" and predicted_effect["stance"] != "supported":
        raise _fail(
            "a matched prediction means the predicted hypothesis gained support",
            category="revision-mismatch",
            field_path=f"effect_on_{locked['hypothesis_id'].lower().replace('-', '_')}.stance",
        )
    if assessment["result"] == "contradicted" and predicted_effect["stance"] == "supported":
        raise _fail(
            "a contradicted prediction cannot leave the predicted hypothesis supported",
            category="revision-mismatch",
            field_path=f"effect_on_{locked['hypothesis_id'].lower().replace('-', '_')}.stance",
        )
    alternatives = payload.get("remaining_alternatives")
    if not isinstance(alternatives, list) or not alternatives:
        raise _fail(
            "remaining_alternatives must be a non-empty list",
            category="missing-field",
            field_path="remaining_alternatives",
        )
    for i, alt in enumerate(alternatives):
        base = f"remaining_alternatives[{i}]"
        if not isinstance(alt, dict) or not alt.get("text"):
            raise _fail("each remaining alternative needs text and refs", category="malformed-item", field_path=base)
        _check_refs(alt.get("refs"), registry, f"{base}.refs")
    questions = payload.get("unresolved_questions")
    if not isinstance(questions, list) or not questions or not all(isinstance(q, str) and q.strip() for q in questions):
        raise _fail(
            "unresolved_questions must be a non-empty list of strings",
            category="missing-field",
            field_path="unresolved_questions",
        )
    nxt = payload.get("next_test")
    if not isinstance(nxt, dict) or not nxt.get("text"):
        raise _fail("next_test needs text and refs", category="malformed-item", field_path="next_test")
    if not isinstance(nxt.get("expected_observations"), str) or not nxt["expected_observations"].strip():
        raise _fail(
            "next_test needs expected observations",
            category="missing-field",
            field_path="next_test.expected_observations",
        )
    _check_refs(nxt.get("refs"), registry, "next_test.refs")
    rec = payload.get("updated_recommendation")
    if not isinstance(rec, dict) or not rec.get("text"):
        raise _fail(
            "updated_recommendation needs text and refs",
            category="malformed-item",
            field_path="updated_recommendation",
        )
    _check_refs(rec.get("refs"), registry, "updated_recommendation.refs")
    if rec.get("requires_human_approval") is not True:
        raise _fail(
            "updated recommendation requires explicit human approval",
            category="missing-approval-flag",
            field_path="updated_recommendation.requires_human_approval",
        )
    if rec.get("executes_production_change", False) is not False:
        raise _fail(
            "assistant must not execute production changes",
            category="production-execution",
            field_path="updated_recommendation.executes_production_change",
        )
    reversal = payload.get("reversal_evidence")
    if not isinstance(reversal, list) or not reversal:
        raise _fail(
            "reversal_evidence must be a non-empty list",
            category="missing-field",
            field_path="reversal_evidence",
        )
    for i, item in enumerate(reversal):
        base = f"reversal_evidence[{i}]"
        if not isinstance(item, dict) or not item.get("text"):
            raise _fail("each reversal item needs text and refs", category="malformed-item", field_path=base)
        _check_refs(item.get("refs"), registry, f"{base}.refs")
    _check_metrics(payload, registry)
    for path, value in (
        ("effect_on_h_ack", effects["H-ACK"]),
        ("effect_on_h_queue", effects["H-QUEUE"]),
        ("updated_recommendation", rec),
        ("reversal_evidence", reversal),
    ):
        _forbids_conclusion(json.dumps(value), path)
    if assessment["result"] not in ("supported", "contradicted", "unresolved"):
        raise _fail("unknown deterministic assessment", category="revision-mismatch", field_path="")
    return payload


def mock_revision_payload() -> dict:
    return {
        "original_prediction": {
            "hypothesis_id": "H-ACK",
            "expected_finding": "ack-found",
            "expected_observation": "Demonstration: the source log holds a case-003 ack missing from the feed.",
        },
        "deterministic_assessment": {"result": "supported"},
        "new_evidence": [
            {"text": "Demonstration: source log holds a case-003 ack missing from the feed.", "refs": ["case-003", "events.csv"]},
        ],
        "effect_on_h_ack": {
            "stance": "supported",
            "scope": "single-case",
            "reason": "Demonstration: the revealed case-003 ack supports a feed-reporting gap for case-003.",
            "refs": ["case-003", "events.csv"],
        },
        "effect_on_h_queue": {
            "stance": "unresolved",
            "scope": "population",
            "reason": "Demonstration: unassigned cases keep queue delays unresolved across the urgent population; no organization-wide root cause is established.",
            "refs": ["case-004", "case-006", "events.csv"],
        },
        "remaining_alternatives": [
            {"text": "Demonstration: queue handling may still explain unassigned cases.", "refs": ["events.csv"]},
        ],
        "unresolved_questions": [
            "Demonstration: does the feed gap affect late-day cases too?",
        ],
        "next_test": {
            "text": "Demonstration: audit feed coverage for late-day cases.",
            "expected_observations": "Demonstration: missing feed entries would extend support; full coverage would isolate case-003.",
            "refs": ["events.csv"],
        },
        "updated_recommendation": {
            "text": "Demonstration: reconcile the feed before changing staffing. No change without approval.",
            "refs": ["case-003", "events.csv"],
            "requires_human_approval": True,
            "executes_production_change": False,
        },
        "reversal_evidence": [
            {"text": "Demonstration: a wider feed audit could show case-003 as isolated.", "refs": ["events.csv"]},
        ],
    }


def produce_revision(adapter, base_dir: str | Path, state: dict, now: int, origin: str) -> dict:
    from .investigation import parse_model_text

    if state.get("status") != "assessed" or not state.get("outcome") or not state.get("assessment"):
        from .experiment import ExperimentError

        raise ExperimentError("revision requires a revealed and assessed experiment", "too-early")
    report = build_case_report(base_dir)
    registry = build_evidence_registry(report)
    locked = state["prediction"]
    outcome = state["outcome"]
    assessment = state["assessment"]
    context = {
        "locked_prediction": locked,
        "revealed_outcome": outcome,
        "deterministic_assessment": assessment,
        "calculations": report["calculations"],
        "contradictions": report["contradictions"],
        "unresolved_questions": report["unresolved_questions"],
    }
    raw = adapter.request_structured(context, build_revision_instructions(registry))
    payload = parse_model_text(raw) if isinstance(raw, str) else raw
    validated = validate_revision(payload, registry, locked, outcome, assessment)
    return {
        "origin": origin,
        "model_id": MODEL_ID if origin == "ai-generated" else "offline-mock",
        "version": 1,
        "generated_at": now,
        "demonstration_only": True,
        "revision": validated,
    }
