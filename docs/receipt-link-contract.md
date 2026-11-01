# MissionReceiptLinkV1 — Contract Design (MC-004b)

Status: CONTRACT-DESIGN milestone. Nothing below is implemented; no new
endpoints, no persistence, no receipt changes were made in MC-004b.

Central finding: the current architecture **cannot answer** "which exact
receipt belongs to this exact mission run." Sharing `case-001` is not
identity. This document records the verified gaps, then proposes the
smallest contract that would close them.

## 1. Current architecture and source references

- Mission identity is a constant: `MISSION_ID = "mission-case-001"`
  (`backend/mission.py:28`). It names a case, not a run.
- Mission state is `{diagnostic, audit_viewed, intervention}`
  (`new_mission_state`, `backend/mission.py:152`). No run/instance field.
- Server state is one in-memory dict: `new_context()`
  (`backend/server.py:87`), installed at startup
  (`Handler.context = new_context()`, `backend/server.py:517`).
  A restart erases everything and recreates a blank run.
- Experiment state (`status/prediction/outcome/assessment/...`) lives in
  the same dict (`new_experiment_state`, `backend/experiment.py:74`).
  `lock_prediction` / `reveal_outcome` / `assess` mutate it in place.
- Receipt creation is decoupled from missions. `write_receipt()` and
  `produce_investigation_with_receipt()` (`backend/receipt.py:80,245`)
  are called from tests and the `receipt` CLI only; `backend/server.py`
  never imports `backend/receipt`, and no route creates, reads, or
  references receipts. There are no `/api/receipt*` routes; the static
  handler never serves `evaluator-private/`.
- A mission can complete without any AI investigation: `mission_report`
  (`backend/mission.py:480`) requires only a recorded intervention
  decision, and predictions may be `human-authored`.
- Stored receipts (`evaluator-private/receipts/1902c485a31f4e45`,
  `10d84a313fd44022`) carry `case_id: case-001` and no mission,
  experiment, prediction, or assessment identifier (proven by
  `ReceiptLinkageTest.test_stored_receipts_lack_mission_linkage`).

## 2. Identity questions — verified answers

1. Instance ID or case ID? Case ID only (`MISSION_ID` constant).
2. Multiple runs per case? Yes — every `new_context()` is a fresh,
   indistinguishable run.
3. Restart behavior? Total erasure, silent blank recreation.
4. Experiment/prediction durable? No — in-memory dict entries.
5. Multiple receipts per case? Yes — random `receipt_id` per
   `write_receipt()` call; same investigation can be receipted twice.
6. Belonging event? None exists anywhere in the codebase.
7. Mission without AI investigation? Yes — fully supported path.
8. Is the investigation hash identity? No — it binds content, not a run;
   identical inputs reproduce it across runs.
9. Receipt-creation authorization? None — any local caller, no mission
   gate, no authentication.
10. Ambiguous/duplicated/missing/mismatched links? No layer handles
    them today; the proposed contract refuses display in all four cases.

## 3. Proposed MissionReceiptLinkV1 schema

A separately stored link record (never inside `receipt.json`, so
historical bytes, hashes, and drift semantics are untouched):

```json
{
  "contract": "MissionReceiptLinkV1",
  "mission_run_id": "mr-...",
  "mission_id": "mission-case-001",
  "case_id": "case-001",
  "experiment_id": "EXP-001",
  "prediction_sha256": "<canonical locked-prediction hash>",
  "receipt_id": "<exact receipt id>",
  "receipt_investigation_sha256": "<as stored in the receipt>",
  "linked_at_utc": "<iso-8601>",
  "link_authority": "human-operator",
  "link_event": "post-assessment-link",
  "status": "active",
  "superseded_by": null
}
```

Field ownership: the server mints `mission_run_id` at run creation and
owns `mission_id/case_id/experiment_id`; the receipt subsystem owns
`receipt_id`/`receipt_investigation_sha256` (read from the stored
receipt, never retyped); the locking subsystem owns `prediction_sha256`
(canonical hash of the locked record, same canonicalization as
`lock_prediction`); the operator owns the link event, timestamp, and
authority via an explicit authorized action. `status/superseded_by` are
owned by the link registry. No field is inferred retroactively — a link
exists only after its explicit creation event.

## 4. Authorized linking sequence (proposed)

1. Mission run reaches `assessed` (feed probe) or audit-viewed
   (timestamp audit) — the same gates as `select_proposal`.
2. Operator invokes the explicit link action naming the exact
   `receipt_id` (a future authorized endpoint; NOT implemented here).
3. Server checks: receipt loads; `verify_receipt` integrity passes;
   `receipt.case_id == run.case_id`; receipt investigation hash equals
   the linked hash; no active link already exists for the run.
4. Server writes the link record to a dedicated link registry
   (server-side, restrictive permissions, outside any served tree).
5. Any later link for the same run marks the old record `superseded`
   (append-only; old records are never edited or deleted).

## 5. Persistence and restart behavior (proposed)

Current state is in-memory, so no run identity can survive today. The
minimal approach, required before any customer deployment:

- At run creation the server mints `mission_run_id` and persists the
  run record (id, case, created-at, state snapshot) to a server-side
  store with restrictive permissions.
- Re-reading the same run returns the same id; completing a mission
  never rotates it.
- Restart reloads persisted runs; an operator starts a new run
  explicitly — never a silent blank reuse.
- Reset/replay mints a new run id, so a previous run's receipt can
  never attach to the new run by accident.
- Concurrent runs hold distinct ids; the link registry keys links by
  `(mission_run_id)`, unique-active enforced.

No persistence was implemented in MC-004b.

## 6. Receipt verification and adjudication rules (proposed)

Link validation, in order, each independently reported:

1. Link record schema/contract version known.
2. Receipt file exists; `receipt_id` exact match (no prefix/fuzzy).
3. Stored investigation rehashes to `receipt_investigation_sha256`.
4. `verify_receipt` integrity check passes (revalidation drift is
   reported as `validator-version-drift`, never as invalidity).
5. `case_id` agreement across run, link, and receipt.
6. Linked prediction hash equals the run's locked prediction hash.
7. Run identity is the authoritative `mission_run_id`, not the case.
8. Link `status == active`, `superseded_by is None`, no conflicting
   active link for the run.
9. Adjudication state is read live from the sidecar
   (`adjudication.json`), never cached into the link; `pending` stays
   `pending`.

Kept separate, always: byte integrity, schema validity,
evidence-manifest match, human adjudication, causal correctness,
engineering authorization, production execution. A matching SHA-256
proves the bytes are unchanged — nothing about correctness.

## 7. Scoped retrieval API design (NOT implemented)

Illustrative shape only, for owner approval before any implementation:

- `GET /api/mission/receipt` — the linked receipt of *this* run only.
  No receipt id in the URL (prevents enumeration); no listing route.
- Prerequisites: authenticated operator session; session owns the run;
  (customer deployment: tenant scope match — absent today, and its
  absence blocks production use).
- Server re-runs the Section 6 checks on every request.
- Minimal response: `receipt_id`, `created_at_utc`, `case_id`,
  non-sensitive `model_config` (id, mode, caps — never keys/prompts),
  `investigation_sha256`, validation result + validator code hash,
  live adjudication state, evidence-manifest hashes.
- Withheld data: any field containing outcome markers is stripped
  unless the run's own reveal authorized it; full investigation text
  is excluded until a display-need is approved.
- Missing/unlinked/unauthorized/mismatched/conflicting states all
  return one generic `404 {error: no-linked-receipt}` — identical
  bytes, so responses do not oracle receipt existence.
- Never: raw file paths, secrets, headers, transport bodies, stack
  traces, or distinct error codes per failure mode.

## 8. Threat model

| Threat | Mitigation | Status |
|---|---|---|
| Cross-tenant disclosure | Tenant-scoped runs + owned-run check | FUTURE — no auth/tenants exist |
| Receipt-ID guessing/enumeration | No id-in-URL, no listing, generic 404 | Contract rule (unimplemented) |
| Case-ID collisions | Run-id authority, never case-only matching | Contract rule |
| Replayed mission identities | Persisted unique run ids, never reused | FUTURE — needs persistence |
| Stale links after reset | Reset mints new run id; old links keyed to old id | Contract rule |
| Conflicting/duplicate links | Unique-active per run, append-only supersede | Contract rule |
| Forged link records | Server-side registry, restrictive perms, no client writes | FUTURE — needs registry |
| Path traversal | Fixed registry dir, id allowlist (`hex{16}`), no path join from input beyond join+resolve check | Contract rule |
| Receipt tampering | Rehash + `verify_receipt` per request | Exists (`receipt.verify_receipt`) |
| Adjudication misrepresentation | Live sidecar read; `pending` default | Exists, needs sidecar-aware display |
| Hidden outcome leakage | Marker stripping; reveal-gated fields | Contract rule |
| Confused deputy (mission vs AI workspace) | Link binds one run; workspace investigations carry no run id unless linked | Contract rule |

## 9. Migration and backward compatibility

- Existing receipts and adjudications are never rewritten, backfilled,
  or re-hashed. The two stored receipts remain valid history with no
  links — displayed as "no verified linkage," exactly as MC-004a does.
- `MissionReceiptLinkV1` records live in a new registry; receipt format
  is unchanged, so `validator-version-drift` semantics are preserved.
- If a V2 contract is ever needed, V1 records stay readable; the
  retrieval layer reports the contract version per link.

## 10. Acceptance criteria

The backend can answer, with passing tests: which exact receipt is
linked to this exact run; which event and authority created the link;
and which of the Section 6 checks pass — while refusing display for
missing, mismatched, conflicting, tampered, unauthenticated, or
unrevealed cases, and while historical receipts stay byte-identical.

## 11. Smallest recommended implementation step (requires owner approval)

Persist a server-minted `mission_run_id` in the mission state
(`new_mission_state`) with run creation/lookup helpers and tests —
in-memory first, disk persistence as the immediate follow-up. No
receipt, link-registry, or endpoint work until run identity exists
and survives a restart test.

Known unknowns: session/auth mechanism for the future endpoint;
production store choice; whether full investigation text may ever be
served; retention/deletion policy for runs and links.
Decisions needing owner approval: authorizing any link-registry or
endpoint implementation; the persistence mechanism; serving any
investigation text to browsers.

## 12. MC-004c update (implemented)

`new_mission_state()` now mints a server-side `mission_run_id`
(`mr-` + 16 hex from `uuid4`) and `GET /api/mission` exposes it;
Mission Control shows it as read-only context. This closes Section 2
items 1–2 (runs are distinguishable) while items 3–4 remain open: state
is still in-memory, so a restart still invalidates the run — the new id
after restart must never be read as a restored mission. No linkage,
registry, endpoint, or persistence was added; Sections 4–7 remain
future work gated on owner approval.

## 13. Amendment V1.1 (MC-008.2) — gap resolutions

No receipt is linked by this amendment. Historical receipts stay
unlinked (proven in `tests/test_mc008_1.py`).

1. Event allowlist: `post-assessment-link` (feed-probe assessed),
   `audit-view-link` (timestamp-audit viewed), `revision-link`
   (approved AI revision). No event type asserts execution —
   approval, execution, and verified outcome stay separate, and no
   execution records exist in this system.
2. Identities: exact `mission_run_id` (regex `mr-[0-9a-f]{16}`),
   exact `receipt_id`, `prediction_sha256` recomputed from the locked
   record, `receipt_investigation_sha256` read from the stored receipt.
3. Revision binding: exact `snapshot_revision` the link was verified
   against, plus proposal id/version and decision as recorded in the
   run's verbatim intervention record (top-level snapshot `proposal`
   is null in production; binding is re-derived, never assumed).
4. Creation provenance: receipt integrity check passes, case ids
   match, prediction/assessment binding re-verified from the run's
   snapshot, operator identity recorded. Supplying matching
   identifiers is not proof; every check must recompute green.
5. Verification states: `verified` (all read-time checks pass),
   `rejected` with reasons (any check fails), `revoked` (operator
   withdrawal; preserved, never deleted). Records never claim a
   state the last verification did not produce.
6. Read-time verification is mandatory: integrity, identity, binding,
   temporal, and schema checks re-run on every read; results are
   reported, never silently cached as verified.
7. Temporal rule: `receipt.created_at_utc` must not predate the
   run's prediction `locked_at`. Ordering is a necessary check, never
   identity by itself.
8. Version handling: unknown link schema or receipt schema versions
   fail closed (`unsupported-version`); pre-V1.1 bodies do not exist
   (no links were ever created), so no migration is needed.
9. Audit-path binding (MC-008.2 refinement): timestamp-audit runs never
   lock a prediction, so `prediction_sha256` is null for `audit-view-link`
   and the temporal check is skipped; binding rests on run identity,
   case, event gate, and full provenance.
10. Revision monotonicity (MC-008.2 refinement): read-time verification
    accepts a strictly newer snapshot of the same run (noted as
    `advanced-revision`) because locks, assessments, and receipts are
    immutable; an older snapshot than the recorded revision is stale
    and rejected. Newness alone still authorizes nothing.

