"""Integrated field-mission demonstration (Task 009). Synthetic only.

One end-to-end Forward Deployed Engineer mission over fictional case-001,
reusing the existing evidence inspector (report), magnitude-aware
statistics, model-assisted investigation, hypothesis comparison, EXP-001
prediction lock/reveal, deterministic assessment, and human decision
recording. No new benchmark, no unrelated features, no production actions.

Mission flow:
  brief -> constraint -> evidence -> hypotheses -> diagnostic choice ->
  (feed-probe: predict -> reveal -> reassess) | (timestamp-audit: result) ->
  intervention decision (approve/reject/defer) -> final report.

Everything runs offline with deterministic fixtures. AI-assisted live
actions stay behind their existing explicit endpoints and are never
invoked by this module.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from .experiment import public_view
from .report import build_case_report

MISSION_ID = "mission-case-001"
# PROP-001 v1 is retired from issuance but preserved: historical decisions
# recorded against it remain valid records and must keep resolving.
HISTORICAL_PROPOSAL_ID = "PROP-001"
HISTORICAL_PROPOSAL_VERSION = "v1"

# Deterministic, versioned proposal selection. The proposal follows the
# diagnostic outcome; a single-case result never authorizes an
# organization-wide fix, so every proposal carries competing problems and a
# bounded scope.
PROPOSALS = {
    "PROP-002": {
        "version": "v1",
        "when": "Feed-probe with ack-found: the source log holds a case-003 "
                "acknowledgment missing from the events feed.",
        "text": ("Bounded acknowledgment-feed reconciliation and tracing: "
                 "reconcile the case-003 source-log acknowledgment (09:40) "
                 "against the events feed using read-only copies, and trace "
                 "whether the same feed gap affects the other supplied rows. "
                 "Scope is bounded to the 7 supplied event rows."),
        "risks": [
            "Tracing may surface feed gaps beyond case-003; wider gaps need "
            "a new decision, not an expanded scope.",
            "Reconciliation uses read-only copies; the production feed is "
            "not altered and no entry is rewritten.",
            "A single case cannot establish an organization-wide root cause; "
            "no fleet-wide remediation is authorized.",
        ],
        "stop_conditions": ("Stop if source-log access requires production "
                            "credentials, or if tracing would leave the 7 "
                            "supplied rows. Nothing is deployed, so there is "
                            "nothing to roll back."),
        "next_role": ("Data-feed owner (unidentified in the supplied "
                      "evidence — confirm the responsible role before acting)."),
    },
    "PROP-003": {
        "version": "v1",
        "when": "Timestamp audit: assignment timing reconciled against the "
                "1-hour rule.",
        "text": ("Bounded assignment-coverage reconciliation: reconcile "
                 "assignment timestamps and overnight coverage against the "
                 "1-hour policy rule for the 7 eligible urgent cases, using "
                 "the verified event log only."),
        "risks": [
            "Coverage review may reclassify the reported overnight-backlog "
            "practice; keep the dispatcher statement visible while checking.",
            "The acknowledgment gap persists for assigned cases, so coverage "
            "work alone cannot close the mission.",
        ],
        "stop_conditions": ("Stop if assignment records require production "
                            "access. Nothing is deployed, so there is nothing "
                            "to roll back."),
        "next_role": "Assignment coordinator (per the policy assignment rule).",
    },
    "PROP-004": {
        "version": "v1",
        "when": "Inconclusive or contrary finding: the locked expectation did "
                "not match the revealed observation.",
        "text": ("Additional verification before any remediation: re-verify "
                 "feed coverage and the locked prediction against the source "
                 "log, and restate the competing explanations. No remediation "
                 "is proposed until verification completes."),
        "risks": [
            "Verification may overturn the working interpretation; acting on "
            "the contradicted expectation would misdirect effort.",
            "Further withheld evidence may be needed before any conclusion.",
        ],
        "stop_conditions": ("Stop and re-scope if verification needs evidence "
                            "outside the supplied rows. Nothing is deployed, "
                            "so there is nothing to roll back."),
        "next_role": ("Investigator on duty (re-check), with the data-feed "
                      "owner to confirm feed coverage."),
    },
}

OTHER_OPEN_PROBLEMS = [
    "2 eligible urgent cases carry no assignment timestamp (queue-handling question stays open).",
    "H-QUEUE is unresolved beyond case-003; a single-case result is support, not proof.",
    "The printer symptom is a reported observation only, not a root cause.",
]
FICTIONAL_NOTICE = (
    "Training demonstration. All people, companies, and events are "
    "fictional. This is not a customer engagement."
)

DIAGNOSTICS = {
    "feed-probe": {
        "id": "feed-probe",
        "title": "Acknowledgment-feed probe (EXP-001)",
        "description": (
            "Check the source log for case-003 to separate queue-handling "
            "assignment delays from an acknowledgment workflow bottleneck. "
            "The outcome is withheld: lock a prediction first, then reveal."
        ),
        "needs_prediction": True,
    },
    "timestamp-audit": {
        "id": "timestamp-audit",
        "title": "Assignment-timestamp audit (deterministic)",
        "description": (
            "Reconcile assignment timestamps against the 1-hour policy rule "
            "using only verified calculations. No withheld outcome, so no "
            "prediction is required."
        ),
        "needs_prediction": False,
    },
}

GLOSSARY = {
    "verified quotation": "Exact text copied from a source document, with document id and character offsets. Rejected if altered.",
    "deterministic calculation": "A number produced by fixed rules from the event log. No AI judgment involved.",
    "prediction lock": "A testable guess recorded with a timestamp before the withheld outcome is revealed. Cannot be edited afterwards.",
    "deterministic assessment": "A rule-based comparison of prediction vs revealed outcome: matched, contradicted, or unresolved. Agreement is support, not proof.",
    "hypothesis": "An unverified interpretation. Never a confirmed failure on its own.",
    "quality flag": "A data oddity (for example possible double-counting) kept as an open question, not a confirmed error.",
}


class MissionError(ValueError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


def new_mission_state() -> dict:
    return {"diagnostic": None, "audit_viewed": False, "intervention": None}


def _experiment_status(ctx: dict) -> str:
    return ctx["experiment"]["status"]


def stage_status(ctx: dict) -> list[dict]:
    """Ordered mission stages with done/current/locked for the stepper."""
    mission = ctx["mission"]
    exp = _experiment_status(ctx)
    diagnostic = mission["diagnostic"]
    predicted = exp in ("prediction locked", "result revealed", "assessed")
    revealed = exp in ("result revealed", "assessed")
    assessed = exp == "assessed"
    audited = mission["audit_viewed"]
    reassessed = assessed or (diagnostic == "timestamp-audit" and audited)
    decided = mission["intervention"] is not None
    stages = [
        ("brief", True),
        ("constraint", True),
        ("evidence", True),
        ("hypotheses", True),
        ("diagnostic", diagnostic is not None),
        ("predict", predicted or diagnostic == "timestamp-audit"),
        ("reveal", revealed or diagnostic == "timestamp-audit"),
        ("reassess", reassessed),
        ("decide", decided),
        ("report", False),
    ]
    out = []
    current_assigned = False
    for name, done in stages:
        if done:
            state = "done"
        elif not current_assigned:
            state = "current"
            current_assigned = True
        else:
            state = "locked"
        out.append({"stage": name, "state": state})
    return out


def mission_view(ctx: dict) -> dict:
    report = build_case_report(ctx["base_dir"])
    return {
        "mission_id": MISSION_ID,
        "fictional_notice": FICTIONAL_NOTICE,
        "brief": (
            "Urgent referrals are going unacknowledged even though the "
            "dispatch system looks healthy. Determine whether assignment "
            "delays or the acknowledgment workflow explain the gap, test "
            "one explanation with a locked prediction, and recommend a "
            "reversible next step. Nothing here changes production."
        ),
        "constraint": report["policy_requirements"],
        "evidence": {
            "calculations": report["calculations"],
            "categories": report.get("categories"),
            "contradictions": report.get("contradictions"),
            "unresolved_questions": report.get("unresolved_questions"),
            "reported_observation_only": report.get("reported_observation_only"),
        },
        "hypotheses": report["hypotheses"],
        "diagnostics": list(DIAGNOSTICS.values()),
        "experiment": public_view(ctx["experiment"]),
        "mission": {
            "diagnostic": ctx["mission"]["diagnostic"],
            "audit_viewed": ctx["mission"]["audit_viewed"],
            "intervention": ctx["mission"]["intervention"],
        },
        "stages": stage_status(ctx),
        "glossary": GLOSSARY,
    }


def choose_diagnostic(ctx: dict, choice: str) -> dict:
    if choice not in DIAGNOSTICS:
        raise MissionError(f"Unknown diagnostic: {choice}.", "bad_request")
    mission = ctx["mission"]
    if mission["diagnostic"] is not None:
        raise MissionError("A diagnostic is already chosen and cannot be changed.", "already-chosen")
    if _experiment_status(ctx) != "proposed":
        raise MissionError("Too late: a prediction is already locked.", "too-late")
    mission["diagnostic"] = choice
    return {"chosen": True, "diagnostic": DIAGNOSTICS[choice]}


def diagnostic_result(ctx: dict) -> dict:
    mission = ctx["mission"]
    choice = mission["diagnostic"]
    if choice is None:
        raise MissionError("Choose a diagnostic first.", "too-early")
    if choice == "feed-probe":
        return {
            "diagnostic": DIAGNOSTICS[choice],
            "requires_prediction": True,
            "experiment": public_view(ctx["experiment"]),
            "note": "Withheld outcome. Lock a prediction before revealing.",
        }
    report = build_case_report(ctx["base_dir"])
    assigned = next(c for c in report["calculations"] if c["label"] == "Assigned within 1 hour")
    eligible = next(c for c in report["calculations"] if c["label"] == "Eligible urgent cases")
    mission["audit_viewed"] = True
    return {
        "diagnostic": DIAGNOSTICS[choice],
        "requires_prediction": False,
        "finding": (
            f"{assigned['value']} of {eligible['value']} eligible urgent cases "
            f"({', '.join(assigned['ids'])}) carry an assignment timestamp within "
            f"the 1-hour policy rule ({assigned['rule']}); the remainder have no "
            "assignment timestamp at all. Assignment delay does not explain the "
            "acknowledgment gap for the assigned cases."
        ),
        "numbers": {"assigned_within_1h": assigned, "eligible": eligible},
        "source": assigned["source"],
        "status": "deterministic result, not an AI judgment",
    }


def select_proposal(ctx: dict) -> tuple[str, dict]:
    """Deterministic proposal selection. Returns (proposal_id, spec)."""
    mission = ctx["mission"]
    experiment = ctx["experiment"]
    if mission["diagnostic"] == "timestamp-audit" and mission["audit_viewed"]:
        return "PROP-003", PROPOSALS["PROP-003"]
    assessment = experiment.get("assessment")
    outcome = experiment.get("outcome") or {}
    if (mission["diagnostic"] == "feed-probe" and assessment is not None
            and outcome.get("finding") == "ack-found"
            and assessment.get("result") == "supported"):
        return "PROP-002", PROPOSALS["PROP-002"]
    if mission["diagnostic"] == "feed-probe" and assessment is not None:
        return "PROP-004", PROPOSALS["PROP-004"]
    raise MissionError(
        "The proposal is shown only after the assessment (feed probe) "
        "or the audit result.", "too-early"
    )


def intervention_proposal(ctx: dict) -> dict:
    """The exact proposal the human is asked to approve, reject, or defer.

    Selected deterministically from the diagnostic outcome: no model call,
    no invented content. Shown before approval; the decision must reference
    its id and version (proposal-to-decision binding)."""
    mission = ctx["mission"]
    experiment = ctx["experiment"]
    proposal_id, spec = select_proposal(ctx)
    basis = [f"diagnostic: {mission['diagnostic']}"]
    if mission["diagnostic"] == "feed-probe":
        outcome = experiment.get("outcome") or {}
        basis.append(f"revealed observation: {outcome.get('finding')}")
        basis.append(f"deterministic assessment: {experiment['assessment'].get('result')}")
        basis.extend(sorted(set(outcome.get("refs", []))))
    else:
        basis.append("deterministic assignment-timestamp reconciliation")
    return {
        "proposal_id": proposal_id,
        "version": spec["version"],
        "layer": "model interpretation",
        "text": spec["text"],
        "supporting_evidence": {
            "refs": basis,
            "requires_human_approval": True,
        },
        "risks": list(spec["risks"]),
        "scope": "Advisory only. No production system is touched, monitored, or changed by this mission.",
        "other_open_problems": list(OTHER_OPEN_PROBLEMS),
        "stop_conditions": spec["stop_conditions"],
        "next_role": spec["next_role"],
        "reversible": True,
        "reversible_basis": "No production change is proposed or executed: there is no action to roll back.",
        "approval_note": (
            "Approval records a human decision on this specific proposal. "
            "It does not deploy anything and does not claim remediation."
        ),
    }


def decide_intervention(ctx: dict, decision: str, note: str = "",
                        proposal_id: str | None = None,
                        proposal_version: str | None = None) -> dict:
    if decision not in ("approve", "reject", "defer"):
        raise MissionError(f"Unknown decision: {decision}.", "bad_request")
    mission = ctx["mission"]
    if mission["intervention"] is not None:
        raise MissionError("An intervention decision is already recorded.", "already-decided")
    ready = _experiment_status(ctx) == "assessed" or (
        mission["diagnostic"] == "timestamp-audit" and mission["audit_viewed"]
    )
    if not ready:
        raise MissionError(
            "Decide only after the assessment (feed probe) or the audit result.", "too-early"
        )
    proposal = intervention_proposal(ctx)
    if proposal_id != proposal["proposal_id"] or proposal_version != proposal["version"]:
        raise MissionError(
            "The decision must reference the current proposal id and version.", "proposal-mismatch"
        )
    cleaned = str(note).strip()
    if not cleaned:
        raise MissionError(
            "A human rationale is required: approve, reject, or defer with a stated reason.",
            "empty-rationale",
        )
    alnum = re.sub(r"[^a-z0-9]", "", cleaned.lower())
    if alnum in ("false", "true", "na", "none") or not alnum:
        raise MissionError(
            "The rationale looks like a placeholder. State the actual reason "
            "for this decision in your own words.",
            "placeholder-rationale",
        )
    mission["intervention"] = {
        "decision": decision,
        "note": str(note).strip()[:500],
        "proposal": proposal,
        "at": int(time.time()),
        "executed": False,
    }
    return {
        "recorded": True,
        "executed": False,
        "proposal_id": proposal["proposal_id"],
        "proposal_version": proposal["version"],
        "message": (
            f"Decision recorded on {proposal['proposal_id']} {proposal['version']}. "
            "Approval alone changes nothing: no production change was "
            "executed and none can be."
        ),
    }


def readable_report(sections: list[dict]) -> list[dict]:
    """Human-readable rendering of each report section as plain labeled
    lines. The browser displays these; the structured sections remain in the
    API for audit. No raw JSON dumps: every line is a sentence or a labeled
    row naming its source."""
    readable = []
    for section in sections:
        title, body = section["title"], section["body"]
        lines: list[str] = []
        if title == "Operating constraints":
            for quote in body:
                lines.append(
                    f"Policy ({quote['doc_id']}, characters {quote['start']}-"
                    f"{quote['end']}): “{quote['quote']}”")
        elif title == "Key evidence and deterministic metrics":
            for calc in body["calculations"]:
                lines.append(
                    f"{calc['label']}: {calc['value']} "
                    f"(denominator: {calc['denominator']}; rule: {calc['rule']}; "
                    f"source: {calc['source']})")
            for contradiction in body.get("contradictions") or []:
                lines.append(f"Contradiction — {contradiction['title']}: "
                             f"{contradiction.get('computed', '')}")
        elif title == "Competing hypotheses":
            for hypothesis in body["report_hypotheses"]:
                lines.append(
                    f"{hypothesis['text']} [{hypothesis.get('status', 'unverified')}; "
                    f"basis: {'; '.join(hypothesis.get('basis', []))}]")
            for hypothesis in body.get("experiment_hypotheses") or []:
                lines.append(f"{hypothesis['id']}: {hypothesis['text']} [unverified]")
        elif title == "Locked prediction and timestamp":
            if isinstance(body, dict):
                lines.append(
                    f"{body.get('origin', 'human-authored')} prediction "
                    f"{body.get('version', '')}: {body['hypothesis_id']} expects "
                    f"{body['expected_finding']} — {body['expected_observation']}")
                lines.append(f"Procedure: {body.get('test_procedure', 'not recorded')}")
                lines.append(f"Criteria: {body['criteria']}")
                lines.append(f"Evidence refs: {', '.join(body['refs'])}")
                lines.append(f"Locked at timestamp {body['locked_at']}; record hash {body['hash']}.")
                if body.get("uncertainty"):
                    lines.append(f"Stated uncertainty: {body['uncertainty']}")
            else:
                lines.append(str(body))
        elif title == "Revealed observation and source":
            if isinstance(body, dict):
                lines.append(f"Revealed: {body.get('finding')} — {body.get('detail', '')}")
                lines.append(f"Source refs: {', '.join(body.get('refs', []))}; "
                             f"revealed at timestamp {body.get('revealed_at')}.")
            else:
                lines.append(str(body))
        elif title == "Deterministic assessment":
            if isinstance(body, dict):
                lines.append(f"Assessment: {body['result']} — {body['reason']}")
                lines.append("A match is support, not proof of a root cause.")
            else:
                lines.append(str(body))
        elif title == "Revised interpretation and remaining uncertainties":
            revision = body["revision"]
            lines.append(revision if isinstance(revision, str)
                         else "A revised interpretation was recorded; see audit record.")
            for question in body["uncertainties"]:
                lines.append(f"Still uncertain: {question}")
        elif title == "Intervention proposal":
            lines.append(f"Proposal {body['proposal_id']} {body['version']}: {body['text']}")
            lines.append(f"Supporting evidence: {', '.join(body['supporting_evidence']['refs'])}")
            for risk in body["risks"]:
                lines.append(f"Risk: {risk}")
            lines.append(f"Scope: {body['scope']}")
            for problem in body["other_open_problems"]:
                lines.append(f"Still open: {problem}")
            lines.append(f"Stop conditions: {body['stop_conditions']}")
            lines.append(f"Next responsible role: {body['next_role']}")
            lines.append(f"Reversible: {body['reversible']} — {body['reversible_basis']}")
        elif title == "Human decision and rationale":
            lines.append(
                f"Decision: {body['decision']} on {body['proposal_id']} "
                f"{body['proposal_version']}, recorded at timestamp {body['recorded_at']}.")
            lines.append(f"Human rationale: {body['rationale']}")
        elif title == "Risk, rollback, and follow-up":
            for risk in body["risks"]:
                lines.append(f"Risk: {risk}")
            lines.append(f"Rollback: {body['rollback']}")
            lines.append(f"Follow-up: {body['follow_up']}")
        elif title == "Production-action confirmation":
            lines.append(f"Executed: {body['executed']} — {body['statement']}")
        else:
            lines.append(str(body) if isinstance(body, str) else "; ".join(
                str(part) for part in ([body] if not isinstance(body, list) else body)))
        readable.append({"title": title, "layer": section["layer"], "lines": lines})
    return readable


def mission_report(ctx: dict) -> dict:
    """Final mission report. Every section carries a layer tag so a reader
    who did not participate can separate confirmed observations, model
    interpretations, deterministic calculations, and human decisions."""
    mission = ctx["mission"]
    if mission["intervention"] is None:
        raise MissionError("Record an intervention decision before the final report.", "too-early")
    view = mission_view(ctx)
    experiment = ctx["experiment"]
    prediction = experiment.get("prediction")
    assessment = experiment.get("assessment")
    revision = experiment.get("revision")
    if prediction is not None:
        prediction_layer = ("human decision" if prediction.get("origin") == "human-authored"
                            else "model interpretation")
    else:
        prediction_layer = "human decision"
    sections = [
        {"title": "Mission objective", "layer": "mission context",
         "body": view["brief"]},
        {"title": "Operating constraints", "layer": "confirmed observation",
         "body": view["constraint"]},
        {"title": "Key evidence and deterministic metrics", "layer": "deterministic calculation",
         "body": {"calculations": view["evidence"]["calculations"],
                  "contradictions": view["evidence"]["contradictions"]}},
        {"title": "Competing hypotheses", "layer": "model interpretation",
         "body": {"report_hypotheses": view["hypotheses"],
                  "experiment_hypotheses":
                      view["experiment"]["definition"].get("hypotheses")}},
        {"title": "Chosen diagnostic test", "layer": "human decision",
         "body": mission["diagnostic"]},
        {"title": "Locked prediction and timestamp", "layer": prediction_layer,
         "body": prediction if prediction is not None else "No prediction required (timestamp audit)."},
        {"title": "Revealed observation and source", "layer": "confirmed observation",
         "body": experiment.get("outcome") if experiment.get("outcome") is not None
         else "No withheld outcome (timestamp audit)."},
        {"title": "Deterministic assessment", "layer": "deterministic calculation",
         "body": assessment if assessment is not None else "Not applicable (timestamp audit)."},
        {"title": "Revised interpretation and remaining uncertainties",
         "layer": "model interpretation",
         "body": {"revision": revision if revision is not None else "No revision requested.",
                  "uncertainties": view["evidence"]["unresolved_questions"]}},
        {"title": "Intervention proposal", "layer": "model interpretation",
         "body": mission["intervention"]["proposal"]},
        {"title": "Human decision and rationale", "layer": "human decision",
         "body": {"decision": mission["intervention"]["decision"],
                  "rationale": mission["intervention"]["note"],
                  "proposal_id": mission["intervention"]["proposal"]["proposal_id"],
                  "proposal_version": mission["intervention"]["proposal"]["version"],
                  "recorded_at": mission["intervention"]["at"]}},
        {"title": "Risk, rollback, and follow-up", "layer": "confirmed observation",
         "body": {"risks": mission["intervention"]["proposal"]["risks"],
                  "rollback": mission["intervention"]["proposal"]["reversible_basis"],
                  "follow_up": ("The named next actor re-runs the chosen diagnostic "
                                "after any operational change and records a new decision; "
                                "this report never closes the investigation by itself.")}},
        {"title": "Production-action confirmation", "layer": "confirmed observation",
         "body": {"executed": False,
                  "statement": "No production action was executed. Approval of the "
                               "proposal is a recorded human decision, not a deployment "
                               "and not a successful remediation."}},
    ]
    return {
        "mission_id": MISSION_ID,
        "fictional_notice": FICTIONAL_NOTICE,
        "sections": sections,
        "readable_sections": readable_report(sections),
        # Compact aliases preserved for existing readers.
        "what_was_tested": view["brief"],
        "diagnostic": mission["diagnostic"],
        "what_was_learned": [
            f"Locked prediction {assessment.get('result')}: {assessment.get('reason')}"
            if assessment else
            "Assignment timestamps reconcile against the 1-hour rule; the "
            "acknowledgment gap persists for assigned cases."
        ],
        "prediction": prediction,
        "assessment": assessment,
        "intervention": mission["intervention"],
        "unresolved": view["evidence"]["unresolved_questions"],
        "quality_flags": [
            "Possible duplicate data is recorded as an unresolved quality "
            "flag, never as confirmed duplication."
        ],
        "limitations": (
            "Single fictional case; offline deterministic fixtures except for "
            "explicitly authorized live AI actions; approval records a human "
            "decision and executes nothing."
        ),
    }
