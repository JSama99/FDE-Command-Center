"""Production MissionSnapshotV1 codec (MC-004e).

Pure encode/decode/validate for durable mission snapshots, per
docs/mission-persistence-contract.md. Standard library only; no
network, no filesystem, no backend mutation. NOT wired to server
startup, transitions, or any API route — the application remains
fully in-memory until a separately authorized integration milestone.

An integrity digest detects accidental or unkeyed modification. It is
not authentication, authorization, or confidentiality, and it must
never be described as proof against an attacker who can rewrite both
content and digest.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .experiment import EXPECTED_FINDINGS, HYPOTHESES

SCHEMA = "MissionSnapshotV1"
MISSION_ID = "mission-case-001"
CASE_ID = "case-001"
EXPERIMENT_ID = "EXP-001"
RUN_RE = re.compile(r"^mr-[0-9a-f]{16}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
ASSESSMENT_RESULTS = ("supported", "contradicted", "unresolved")
DECISIONS = ("approve", "reject", "defer")

_BODY_KEYS = ("schema", "snapshot_revision", "saved_at_utc",
              "mission_run_id", "mission_id",
              "case_id", "experiment_id", "lifecycle_stage", "mission",
              "prediction", "outcome", "assessment", "proposal",
              "intervention", "source_manifest",
              "revision", "revision_validation", "approvals")
# MC-007.2: bodies written before the revision/approval extension lack the
# last three keys and are rejected as "bad-schema" (fail closed). No
# durable snapshots predate this extension — the store was never wired —
# so no migration path is needed.


class SnapshotError(ValueError):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def derive_stage(body: dict[str, Any]) -> str:
    """Lifecycle label recomputed from records, never trusted from disk."""
    if body.get("intervention") is not None:
        return "decided"
    if body.get("assessment") is not None:
        return "assessed"
    if body.get("outcome") is not None:
        return "result revealed"
    if body.get("prediction") is not None:
        return "prediction locked"
    mission = body.get("mission") or {}
    if mission.get("diagnostic") is not None or mission.get("audit_viewed"):
        return "diagnostic selected"
    return "proposed"


def build_snapshot(ctx: dict[str, Any], manifest: dict[str, str],
                   revision: int, now: str) -> dict[str, Any]:
    """Construct an unsigned snapshot body from authoritative state.

    The timestamp is caller-supplied (ISO-8601) so the codec stays pure
    and deterministic; ordering authority comes from the revision, the
    timestamp is informational.
    """
    if not isinstance(revision, int) or revision < 1:
        raise SnapshotError("revision must be a positive integer",
                            "bad-revision")
    if not isinstance(now, str) or not now.strip():
        raise SnapshotError("snapshot timestamp required", "bad-timestamp")
    mission = ctx["mission"]
    experiment = ctx["experiment"]
    body: dict[str, Any] = {
        "schema": SCHEMA,
        "snapshot_revision": revision,
        "saved_at_utc": now.strip(),
        "mission_run_id": mission["mission_run_id"],
        "mission_id": MISSION_ID,
        "case_id": CASE_ID,
        "experiment_id": EXPERIMENT_ID,
        "lifecycle_stage": "",
        "mission": {"diagnostic": mission["diagnostic"],
                    "audit_viewed": mission["audit_viewed"]},
        "prediction": experiment.get("prediction"),
        "outcome": experiment.get("outcome"),
        "assessment": experiment.get("assessment"),
        "proposal": None,
        "intervention": mission["intervention"],
        "source_manifest": dict(manifest),
        "revision": experiment.get("revision"),
        "revision_validation": experiment.get("revision_validation"),
        "approvals": [dict(a) for a in ctx.get("approvals", [])],
    }
    body["lifecycle_stage"] = derive_stage(body)
    return body


def attach_proposal(body: dict[str, Any], proposal_id: str,
                    version: str) -> dict[str, Any]:
    """Record the derived proposal id/version alongside the snapshot."""
    if body.get("proposal") is not None:
        raise SnapshotError("proposal already recorded", "duplicate-field")
    out = dict(body)
    out["proposal"] = {"proposal_id": proposal_id, "version": version}
    return out


def encode_snapshot(body: dict[str, Any]) -> bytes:
    """Canonical bytes for storage, with integrity digest included."""
    unsigned = {k: body[k] for k in _BODY_KEYS if k in body}
    digest = _sha256(_canonical(unsigned))
    signed = dict(unsigned)
    signed["snapshot_sha256"] = digest
    return _canonical(signed)


def _require(condition: bool, message: str, code: str) -> None:
    if not condition:
        raise SnapshotError(message, code)


def _check_prediction(pred: Any) -> None:
    _require(isinstance(pred, dict), "prediction must be an object",
             "bad-prediction")
    for key in ("hypothesis_id", "expected_finding", "expected_observation",
                "criteria", "refs", "locked_at", "hash"):
        _require(key in pred, f"prediction missing {key}", "bad-prediction")
    _require(pred["hypothesis_id"] in HYPOTHESES, "unknown hypothesis id",
             "bad-prediction")
    _require(pred["expected_finding"] in EXPECTED_FINDINGS,
             "unknown expected finding", "bad-prediction")
    _require(isinstance(pred["refs"], list) and pred["refs"]
             and all(isinstance(r, str) and r for r in pred["refs"]),
             "prediction refs must be non-empty", "bad-prediction")
    _require(isinstance(pred["hash"], str) and HEX64_RE.match(pred["hash"]),
             "prediction hash malformed", "bad-prediction")
    recomputed = _sha256(_canonical(
        {k: v for k, v in pred.items() if k != "hash"}))
    _require(recomputed == pred["hash"], "prediction hash mismatch",
             "bad-prediction")


def _check_outcome(out: Any) -> None:
    _require(isinstance(out, dict), "outcome must be an object",
             "bad-outcome")
    _require(out.get("finding") in EXPECTED_FINDINGS,
             "unknown outcome finding", "bad-outcome")


def _check_assessment(value: Any) -> None:
    _require(isinstance(value, dict), "assessment must be an object",
             "bad-assessment")
    _require(value.get("result") in ASSESSMENT_RESULTS,
             "unknown assessment result", "bad-assessment")
    _require(isinstance(value.get("refs"), list) and value["refs"],
             "assessment refs must be non-empty", "bad-assessment")


def _check_intervention(value: Any, proposal: Any) -> None:
    _require(isinstance(value, dict), "intervention must be an object",
             "bad-decision")
    _require(value.get("decision") in DECISIONS, "unknown decision",
             "bad-decision")
    _require(isinstance(value.get("note"), str) and value["note"].strip(),
             "decision rationale required", "bad-decision")
    _require(value.get("executed") is False,
             "snapshot must never record execution", "bad-decision")
    linked = value.get("proposal") or {}
    _require(isinstance(linked, dict), "decision proposal record malformed",
             "bad-decision")
    if proposal is not None:
        _require(linked.get("proposal_id") == proposal.get("proposal_id")
                 and linked.get("version") == proposal.get("version"),
                 "decision not bound to recorded proposal", "bad-binding")


def _check_revision(value: Any, prediction: Any, assessment: Any) -> None:
    """Structural + binding checks for a stored AI revision envelope."""
    _require(isinstance(value, dict), "revision must be an object",
             "bad-revision-record")
    for key in ("origin", "model_id", "version", "generated_at",
                "demonstration_only", "revision"):
        _require(key in value, f"revision missing {key}",
                 "bad-revision-record")
    _require(isinstance(value["origin"], str) and value["origin"],
             "revision origin malformed", "bad-revision-record")
    _require(isinstance(value["model_id"], str) and value["model_id"],
             "revision model identity malformed", "bad-revision-record")
    _require(isinstance(value.get("version"), int)
             and not isinstance(value.get("version"), bool)
             and value["version"] >= 1,
             "revision version malformed", "bad-revision-record")
    _require(isinstance(value.get("generated_at"), int),
             "revision timestamp malformed", "bad-revision-record")
    _require(isinstance(value.get("demonstration_only"), bool),
             "revision demonstration flag malformed", "bad-revision-record")
    inner = value["revision"]
    _require(isinstance(inner, dict) and inner,
             "revision content malformed", "bad-revision-record")
    # A revision is only producible over a locked prediction and a
    # recorded assessment; a stored revision without them is incoherent.
    _require(prediction is not None and assessment is not None,
             "revision without locked prediction and assessment",
             "gated")
    orig = inner.get("original_prediction") or {}
    _require(orig.get("hypothesis_id")
             == (prediction or {}).get("hypothesis_id")
             and orig.get("expected_finding")
             == (prediction or {}).get("expected_finding"),
             "revision not bound to the locked prediction",
             "bad-binding")
    _require((inner.get("deterministic_assessment") or {}).get("result")
             == (assessment or {}).get("result"),
             "revision not bound to the recorded assessment",
             "bad-binding")


def _check_human_record(value: Any, code: str, decisions: tuple) -> None:
    _require(isinstance(value, dict), "human record must be an object",
             code)
    _require(value.get("decision") in decisions, "unknown human decision",
             code)
    _require(isinstance(value.get("note"), str),
             "human rationale malformed", code)
    _require(isinstance(value.get("at"), int),
             "human record timestamp malformed", code)
    _require(value.get("executed") is False,
             "snapshot must never record execution", code)


def decode_snapshot(raw: bytes | str) -> dict[str, Any]:
    """Parse, digest-verify, and fully validate a stored snapshot.

    Every invariant below is self-contained: anything requiring live
    state (proposal recomputation, manifest equality) belongs in
    verify_against_live, not here.
    """
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError("snapshot bytes are not valid JSON",
                            "corrupt") from exc
    _require(isinstance(body, dict), "snapshot must be an object",
             "corrupt")
    digest = body.get("snapshot_sha256")
    _require(isinstance(digest, str) and HEX64_RE.match(digest),
             "integrity digest malformed", "bad-digest")
    unsigned = {k: body[k] for k in _BODY_KEYS if k in body}
    _require(_sha256(_canonical(unsigned)) == digest,
             "integrity digest mismatch", "bad-digest")
    _require(body.get("schema") == SCHEMA, "unsupported schema version",
             "bad-schema")
    _require("revision" in body and "revision_validation" in body
             and "approvals" in body,
             "snapshot predates the revision/approval extension",
             "bad-schema")
    _require(isinstance(body.get("snapshot_revision"), int)
             and not isinstance(body.get("snapshot_revision"), bool)
             and body["snapshot_revision"] >= 1,
             "revision must be a positive integer", "bad-revision")
    _require(isinstance(body.get("saved_at_utc"), str)
             and body["saved_at_utc"].strip(),
             "snapshot timestamp required", "bad-timestamp")
    _require(isinstance(body.get("mission_run_id"), str)
             and RUN_RE.match(body["mission_run_id"]),
             "mission run identity malformed", "bad-identity")
    _require(body.get("mission_id") == MISSION_ID, "mission id mismatch",
             "bad-identity")
    _require(body.get("case_id") == CASE_ID, "case id mismatch",
             "bad-identity")
    _require(body.get("experiment_id") == EXPERIMENT_ID,
             "experiment id mismatch", "bad-identity")
    mission = body.get("mission")
    _require(isinstance(mission, dict), "lifecycle record malformed",
             "bad-lifecycle")
    _require(set(mission) == {"diagnostic", "audit_viewed"},
             "unexpected lifecycle fields", "bad-lifecycle")
    _require(mission.get("diagnostic") in (None, "feed-probe",
                                           "timestamp-audit"),
             "unknown diagnostic", "bad-lifecycle")
    _require(isinstance(mission.get("audit_viewed"), bool),
             "audit flag malformed", "bad-lifecycle")
    _require(derive_stage(body) == body.get("lifecycle_stage"),
             "lifecycle stage inconsistent with records",
             "bad-lifecycle")
    if body.get("prediction") is not None:
        _check_prediction(body["prediction"])
    if body.get("outcome") is not None:
        _require(body.get("prediction") is not None,
                 "outcome without locked prediction", "gated")
        _check_outcome(body["outcome"])
    if body.get("assessment") is not None:
        _require(body.get("outcome") is not None,
                 "assessment without revealed outcome", "gated")
        _check_assessment(body["assessment"])
    if body.get("revision") is not None:
        _check_revision(body["revision"], body.get("prediction"),
                        body.get("assessment"))
    if body.get("revision_validation") is not None:
        _require(body.get("revision") is not None,
                 "revision validation without a stored revision", "gated")
        _check_human_record(body["revision_validation"],
                            "bad-revision-validation", ("approve", "reject"))
    approvals = body.get("approvals")
    _require(isinstance(approvals, list),
             "approvals record malformed", "bad-approvals")
    for entry in approvals:
        _check_human_record(entry, "bad-approvals", ("approve", "reject"))
    proposal = body.get("proposal")
    if proposal is not None:
        _require(isinstance(proposal, dict)
                 and set(proposal) == {"proposal_id", "version"}
                 and isinstance(proposal.get("proposal_id"), str)
                 and isinstance(proposal.get("version"), str),
                 "proposal record malformed", "bad-proposal")
    if body.get("intervention") is not None:
        _check_intervention(body["intervention"], proposal)
    manifest = body.get("source_manifest")
    _require(isinstance(manifest, dict) and manifest
             and all(isinstance(k, str) and isinstance(v, str)
                     and HEX64_RE.match(v) for k, v in manifest.items()),
             "source manifest malformed", "bad-manifest")
    return body


def verify_against_live(ctx: dict[str, Any], manifest: dict[str, str],
                        body: dict[str, Any]) -> dict[str, str]:
    """Recheck a decoded snapshot against authoritative live state.

    Recomputes proposal binding and manifest identity instead of
    trusting the stored bytes. Raises SnapshotError on any mismatch.
    """
    from .mission import select_proposal

    checks: dict[str, str] = {}
    live_run = ctx["mission"]["mission_run_id"]
    _require(body["mission_run_id"] == live_run, "run identity mismatch",
             "run-mismatch")
    checks["run"] = "authoritative"
    live_pred = ctx["experiment"].get("prediction")
    if body.get("prediction") is not None:
        _require(live_pred == body["prediction"],
                 "locked prediction differs from live record",
                 "prediction-mismatch")
        checks["prediction"] = "verbatim"
    if body.get("proposal") is not None:
        proposal_id, spec = select_proposal(ctx)
        _require(body["proposal"] == {"proposal_id": proposal_id,
                                      "version": spec["version"]},
                 "proposal binding differs from live derivation",
                 "proposal-mismatch")
        checks["proposal"] = "bound"
    _require(dict(manifest) == body["source_manifest"],
             "source manifest differs from pinned fixtures",
             "manifest-mismatch")
    checks["manifest"] = "pinned"
    _require(derive_stage(body) == derive_stage({
        "mission": {"diagnostic": ctx["mission"]["diagnostic"],
                    "audit_viewed": ctx["mission"]["audit_viewed"]},
        "prediction": live_pred,
        "outcome": ctx["experiment"].get("outcome"),
        "assessment": ctx["experiment"].get("assessment"),
        "intervention": ctx["mission"]["intervention"],
    }), "lifecycle stage differs from live state", "stage-mismatch")
    checks["stage"] = "consistent"
    return checks
