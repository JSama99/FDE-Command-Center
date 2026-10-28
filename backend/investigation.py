"""Structured investigation over verified evidence (Task 004).

Model context is built ONLY from verified quotations and deterministic
calculations produced by the existing backend. Model output is parsed as JSON
(never executed) and every evidence reference is validated against the backend
evidence registry.

Claim levels, kept distinct:
- observation: something seen in the evidence (quote or computed value).
- hypothesis: an unverified reading that cites its basis.
- supported finding: backend stamp for a claim backed by a formal policy
  quote AND a computed value. Only the backend assigns this, never the model.
- validated conclusion: backend stamp after validation plus human approval.
  Never present in model output; rejected there.

Stakeholder reports (dispatcher/manager) are never independently verified
behavior: any observation citing them must declare basis
"stakeholder-report" and must not claim "verified-behavior".

Human approval is required for any corrective action: the provisional
recommendation must carry requires_human_approval=True and
executes_production_change=False. This module contains no code path that
executes production changes.
"""

from __future__ import annotations

from pathlib import Path

from .meta_adapter import MalformedResponseError
from .report import build_case_report

EXPECTED_SECTIONS = (
    "observations",
    "competing_hypotheses",
    "unresolved_questions",
    "diagnostic_experiments",
    "provisional_recommendation",
    "counter_evidence",
)

OBSERVATION_BASES = ("verified-quote", "computed", "stakeholder-report")

# Refs the model may cite: source documents plus computed case ids.
DOC_REFS = ("policy", "dispatcher", "manager", "events.csv", "ledger")

# The printer symptom stays irrelevant unless later evidence connects it.
PRINTER_MARKERS = ("printer", "floor-2")


class InvestigationValidationError(ValueError):
    pass


class DiagnosticError(InvestigationValidationError):
    """A validation rejection carrying safe diagnostic fields.

    Only the rule category, schema field path, and rejected reference leave
    the backend. Rejected model text, prompts, and credentials never do.
    """

    def __init__(self, message: str, *, stage: str, category: str, field_path: str = "", ref: str = "") -> None:
        super().__init__(message)
        self.stage = stage
        self.category = category
        self.field_path = field_path
        self.ref = ref


def _fail(message: str, *, category: str, field_path: str = "", ref: str = "") -> DiagnosticError:
    return DiagnosticError(
        message, stage="evidence-validation", category=category, field_path=field_path, ref=ref
    )


def diagnostic_report(exc: BaseException, correlation_id: str, failed_at: str) -> dict:
    """Safe diagnostic record: rule metadata only, never model text or secrets."""
    if isinstance(exc, DiagnosticError):
        category, field_path, ref = exc.category, exc.field_path, exc.ref
    else:
        category, field_path, ref = type(exc).__name__, "", ""
    return {
        "stage": "evidence-validation" if failed_at == "evidence-validation" else "response-parsing",
        "category": category,
        "field_path": field_path,
        "ref": ref,
        "correlation_id": correlation_id,
        "failed_at": failed_at,
    }


def build_evidence_registry(report: dict) -> dict:
    cases = set(report.get("categories", {}).get("eligible", []))
    cases.update(report.get("categories", {}).get("with_assignment", []))
    cases.update(report.get("categories", {}).get("valid_ack_within_4h", []))
    cases.update(report.get("categories", {}).get("confirmed_miss", []))
    cases.update(report.get("categories", {}).get("anomalous", []))
    cases.update(report.get("categories", {}).get("incomplete", []))
    metrics = {c["label"]: c["value"] for c in report.get("calculations", [])}
    quotes = {}
    for group in ("policy_requirements", "dispatcher_statements", "manager_statements"):
        for q in report.get(group, []):
            quotes[q["quote"]] = {"doc_id": q["doc_id"], "start": q["start"], "end": q["end"]}
    return {"docs": set(DOC_REFS), "cases": cases, "metrics": metrics, "quotes": quotes}


def build_instructions(registry: dict) -> str:
    """Model instructions generated from the same contract the validator enforces.

    Allowed reference IDs, the exact output schema, the permitted metric
    labels and values, and the status rules below are drawn from the shared
    constants and the backend evidence registry, so the prompt and the
    validator cannot drift apart.
    """
    doc_refs = ", ".join(f'"{r}"' for r in sorted(DOC_REFS))
    case_refs = ", ".join(f'"{c}"' for c in sorted(registry["cases"]))
    metric_lines = "\n".join(
        f'- "{label}": {value}' for label, value in sorted(registry["metrics"].items())
    )
    bases = ", ".join(f'"{b}"' for b in OBSERVATION_BASES)
    sections = ", ".join(EXPECTED_SECTIONS)
    return (
        "Return a single JSON object with exactly these top-level keys: "
        f"{sections}.\n"
        "Schema (all fields required unless noted):\n"
        '- observations: [{"text": string, "refs": [ref...], "basis": one of '
        f"{bases}}}]. Every observation needs text, refs, and basis.\n"
        '- competing_hypotheses: [{"text": string, "refs": [ref...], '
        '"status": "hypothesis"}]. Every hypothesis keeps status "hypothesis".\n'
        "- unresolved_questions: [string, ...] (non-empty).\n"
        '- diagnostic_experiments: [{"text": string, "refs": [ref...]}].\n'
        "- provisional_recommendation: {\"text\": string, \"refs\": [ref...], "
        '"requires_human_approval": true, "executes_production_change": false}.\n'
        '- counter_evidence: [{"text": string, "refs": [ref...]}].\n'
        '- metrics (optional): an object using only the labels below with exactly '
        "the backend-computed values. Put numbers only here, nowhere else.\n"
        f"Allowed evidence references and nothing else. Documents: {doc_refs}. "
        f"Cases: {case_refs}.\n"
        "Permitted numerical claims (exact labels and values):\n"
        f"{metric_lines}\n"
        "Stakeholder-report rule: any observation citing dispatcher or manager "
        'must use basis "stakeholder-report". Stakeholder reports are never '
        'independently verified behavior; basis "verified-quote" is only for '
        "policy citations.\n"
        "Status rules: hypotheses stay \"hypothesis\"; never write status "
        '"validated conclusion" — validation and conclusions are backend stamps '
        "issued after human review.\n"
        "Printer rule: the reported printer symptom is irrelevant. Never use it "
        "as a cause in hypotheses or recommendations.\n"
        "Use only the evidence provided below. Do not invent references, cases, or numbers."
    )


def build_model_context(report: dict) -> dict:
    """Context for the model: verified quotes + deterministic numbers only."""
    return {
        "case_id": report["case_id"],
        "policy_requirements": report["policy_requirements"],
        "dispatcher_statements": report["dispatcher_statements"],
        "manager_statements": report["manager_statements"],
        "calculations": report["calculations"],
        "contradictions": report["contradictions"],
        "unresolved_questions": report["unresolved_questions"],
        "reported_observation_only": report["reported_observation_only"],
        "rules": report["generated_from"],
    }


def _check_refs(refs: object, registry: dict, field_path: str) -> list[str]:
    if not isinstance(refs, list) or not refs or not all(isinstance(r, str) and r for r in refs):
        raise _fail(
            "item must carry a non-empty list of evidence references",
            category="missing-refs",
            field_path=field_path,
        )
    for ref in refs:
        if ref in registry["docs"] or ref in registry["cases"]:
            continue
        raise _fail(
            f"cites unknown evidence reference: {ref!r}",
            category="unknown-reference",
            field_path=field_path,
            ref=ref,
        )
    return refs


def _check_metrics(payload: dict, registry: dict) -> None:
    metrics = payload.get("metrics", {})
    if not isinstance(metrics, dict):
        raise _fail("metrics must be an object when present", category="bad-metrics-type", field_path="metrics")
    for label, value in metrics.items():
        if label not in registry["metrics"]:
            raise _fail(
                f"unsupported numerical claim: {label!r}",
                category="unknown-metric",
                field_path=f"metrics.{label}",
            )
        if value != registry["metrics"][label]:
            raise _fail(
                f"numerical claim says {value!r} but backend computed {registry['metrics'][label]!r}",
                category="metric-mismatch",
                field_path=f"metrics.{label}",
            )


def _mentions_printer(text: str) -> bool:
    lowered = text.lower()
    return any(m in lowered for m in PRINTER_MARKERS)


def validate_investigation(payload: object, registry: dict) -> dict:
    if not isinstance(payload, dict):
        raise _fail("investigation must be a JSON object", category="malformed-item", field_path="")
    missing = [s for s in EXPECTED_SECTIONS if s not in payload]
    if missing:
        raise _fail(
            f"investigation is missing sections: {missing}",
            category="missing-section",
            field_path=",".join(missing),
        )

    for i, item in enumerate(payload["observations"]):
        base = f"observations[{i}]"
        if not isinstance(item, dict) or "text" not in item or "refs" not in item:
            raise _fail("each observation needs text and refs", category="malformed-item", field_path=base)
        refs = _check_refs(item["refs"], registry, f"{base}.refs")
        basis = item.get("basis", "")
        if basis not in OBSERVATION_BASES:
            raise _fail(
                "each observation must declare basis",
                category="missing-field",
                field_path=f"{base}.basis",
            )
        stakeholders = {"dispatcher", "manager"} & set(refs)
        if stakeholders and basis != "stakeholder-report":
            raise _fail(
                "stakeholder reports must not be presented as independently verified behavior",
                category="stakeholder-misattribution",
                field_path=f"{base}.basis",
            )
        if "policy" in refs and basis != "verified-quote":
            raise _fail(
                "policy citations back formal claims, not computed text",
                category="policy-misattribution",
                field_path=f"{base}.basis",
            )
        if item.get("status") == "validated conclusion":
            raise _fail(
                "model output must not claim validated conclusion",
                category="forbidden-conclusion",
                field_path=f"{base}.status",
            )
        if _mentions_printer(item["text"]):
            if "manager" not in refs or basis != "stakeholder-report":
                raise _fail(
                    "printer symptom may only appear as an attributed stakeholder report",
                    category="printer-causal",
                    field_path=base,
                )

    for i, item in enumerate(payload["competing_hypotheses"]):
        base = f"competing_hypotheses[{i}]"
        if not isinstance(item, dict) or "text" not in item or "refs" not in item:
            raise _fail("each hypothesis needs text and refs", category="malformed-item", field_path=base)
        _check_refs(item["refs"], registry, f"{base}.refs")
        if item.get("status", "hypothesis") != "hypothesis":
            raise _fail(
                "competing hypotheses stay hypotheses until validated",
                category="hypothesis-status",
                field_path=f"{base}.status",
            )
        if _mentions_printer(item["text"]):
            raise _fail(
                "printer symptom must stay irrelevant without new evidence",
                category="printer-causal",
                field_path=base,
            )

    if not isinstance(payload["unresolved_questions"], list) or not payload["unresolved_questions"]:
        raise _fail(
            "unresolved_questions must be a non-empty list",
            category="unresolved-empty",
            field_path="unresolved_questions",
        )

    for i, item in enumerate(payload["diagnostic_experiments"]):
        base = f"diagnostic_experiments[{i}]"
        if not isinstance(item, dict) or "text" not in item or "refs" not in item:
            raise _fail("each experiment needs text and refs", category="malformed-item", field_path=base)
        _check_refs(item["refs"], registry, f"{base}.refs")

    rec = payload["provisional_recommendation"]
    if not isinstance(rec, dict) or "text" not in rec or "refs" not in rec:
        raise _fail(
            "provisional_recommendation needs text and refs",
            category="malformed-item",
            field_path="provisional_recommendation",
        )
    _check_refs(rec["refs"], registry, "provisional_recommendation.refs")
    if rec.get("requires_human_approval") is not True:
        raise _fail(
            "corrective action requires explicit human approval",
            category="missing-approval-flag",
            field_path="provisional_recommendation.requires_human_approval",
        )
    if rec.get("executes_production_change", False) is not False:
        raise _fail(
            "assistant must not execute production changes",
            category="production-execution",
            field_path="provisional_recommendation.executes_production_change",
        )
    if _mentions_printer(rec["text"]):
        raise _fail(
            "printer symptom must stay irrelevant without new evidence",
            category="printer-causal",
            field_path="provisional_recommendation",
        )

    for i, item in enumerate(payload["counter_evidence"]):
        base = f"counter_evidence[{i}]"
        if not isinstance(item, dict) or "text" not in item or "refs" not in item:
            raise _fail("each counter-evidence item needs text and refs", category="malformed-item", field_path=base)
        _check_refs(item["refs"], registry, f"{base}.refs")

    _check_metrics(payload, registry)
    return payload


def classify_claim(item: dict, registry: dict) -> str:
    """Backend claim-level stamp. Model output only ever yields the first two."""
    refs = set(item.get("refs", []))
    if item.get("status") == "hypothesis":
        return "hypothesis"
    if "policy" in refs and "events.csv" in refs:
        return "supported finding"
    return "observation"


def build_offline_investigation(base_dir: str | Path = ".") -> dict:
    """Deterministic offline investigation for UI testing without API calls.

    Constructed only from the verified report (quotes + computed categories),
    then passed through the same validator as model output. Contains no model
    text and no new numbers.
    """
    report = build_case_report(base_dir)
    registry = build_evidence_registry(report)
    metrics = {
        label: registry["metrics"][label]
        for label in ("Eligible urgent cases", "Confirmed deadline misses")
    }
    payload = {
        "observations": [
            {
                "text": "Policy requires urgent assignment within 1 hour of creation.",
                "refs": ["policy"],
                "basis": "verified-quote",
            },
            {
                "text": "Policy requires a recorded acknowledgment within 4 hours of creation.",
                "refs": ["policy"],
                "basis": "verified-quote",
            },
            {
                "text": "1 of 7 eligible urgent cases has a valid acknowledgment within 4 hours; "
                "3 are confirmed misses.",
                "refs": ["events.csv"],
                "basis": "computed",
            },
            {
                "text": "Dispatcher reports leaving urgent cases unassigned overnight.",
                "refs": ["dispatcher"],
                "basis": "stakeholder-report",
            },
            {
                "text": "Manager states no urgent case ever waits unassigned.",
                "refs": ["manager"],
                "basis": "stakeholder-report",
            },
        ],
        "competing_hypotheses": [
            {
                "text": "Fictional reading: overnight backlog explains the unassigned urgent cases.",
                "refs": ["dispatcher", "events.csv"],
                "status": "hypothesis",
            },
            {
                "text": "Fictional reading: same-day acknowledgment still misses the 4-hour deadline.",
                "refs": ["dispatcher", "case-002"],
                "status": "hypothesis",
            },
        ],
        "unresolved_questions": list(report["unresolved_questions"]),
        "diagnostic_experiments": [
            {
                "text": "Extend observation windows for case-005 and case-006, then recompute.",
                "refs": ["events.csv"],
            },
            {
                "text": "Reconcile the case-008 timestamps against the source log.",
                "refs": ["case-008"],
            },
        ],
        "provisional_recommendation": {
            "text": "Fictional suggestion: review overnight assignment coverage. "
            "No change without human approval.",
            "refs": ["events.csv", "dispatcher"],
            "requires_human_approval": True,
            "executes_production_change": False,
        },
        "counter_evidence": [
            {"text": "case-001 met both deadlines, so the path can work.", "refs": ["case-001"]},
        ],
        "metrics": metrics,
    }
    validated = validate_investigation(payload, registry)
    return {
        "case_id": report["case_id"],
        "mode": "offline-mock",
        "investigation": validated,
        "note": "Deterministic offline investigation for UI testing. No model was called. "
        "Hypotheses are unverified interpretations. Corrective action requires human "
        "approval; nothing was executed.",
    }


def parse_model_text(raw: str) -> dict:
    import json as _json

    try:
        parsed = _json.loads(raw)
    except _json.JSONDecodeError as exc:
        raise MalformedResponseError(f"model returned malformed JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise MalformedResponseError("model response must be a JSON object")
    return parsed


def produce_investigation(adapter, base_dir: str | Path = ".") -> dict:
    """Build context from the verified report, request, parse, and validate.

    Instructions are generated from the same registry the validator enforces,
    so the model is told the exact schema, allowed references, permitted
    numbers, and status rules it will be graded against.
    """
    report = build_case_report(base_dir)
    registry = build_evidence_registry(report)
    context = build_model_context(report)
    instructions = build_instructions(registry)
    raw = adapter.request_structured(context, instructions)
    payload = parse_model_text(raw) if isinstance(raw, str) else raw
    validated = validate_investigation(payload, registry)
    return {
        "case_id": report["case_id"],
        "levels": {s: ("hypothesis" if s == "competing_hypotheses" else "observation") for s in EXPECTED_SECTIONS},
        "investigation": validated,
        "note": "Model output validated against backend evidence. "
        "Supported findings and validated conclusions are backend stamps issued after human review, "
        "never model claims. Corrective action requires human approval; nothing was executed.",
    }
