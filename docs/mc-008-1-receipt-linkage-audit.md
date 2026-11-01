# MC-008.1 — Mission Receipt Linkage Architecture Audit

Status: AUDIT ONLY. No linkage activated, no product code changed.
Tests added: `tests/test_mc008_1.py` (4 fact-establishing tests).
Suite: 621 tests OK (617 baseline + 4), 1 pre-existing socket skip.

## 1. Verified receipt architecture (`backend/receipt.py`)

Creation: `write_receipt` revalidates the investigation against a fresh
registry, mints `receipt_id` (uuid hex16), and stores `receipt.json`
under `evaluator-private/receipts/<id>/` (0700/0600). Record:
`receipt_id`, `created_at_utc`, `case_id`, `synthetic`, `model_config`
(locally recorded, explicitly not provider-attested),
`investigation_sha256`, `evidence_manifest`, validated `investigation`,
validation record with validator code hash, `adjudication_status`.
Review: `verify_receipt` checks integrity, code-drift
(`validator-version-drift` vs invalid), revalidation, and evidence
match — never modifies. Adjudication: `record_adjudication` writes a
separate sidecar; originals are never overwritten. Receipt creation is
decoupled from the mission flow (`produce_investigation_with_receipt`
is opt-in; the server never calls it).

Proven by test: both historical receipts carry `case_id` only — no
`mission_run_id`, experiment, prediction, proposal, decision, or link
field anywhere in record or investigation content — and both pass
integrity verification.

## 2. Verified mission identity architecture

Authoritative, stable, snapshot-persisted: server-minted `mission_run_id`
(`mr-…`, durable since MC-007.3), fixed mission/case/experiment ids,
verbatim locked prediction with recomputed hash, outcome, assessment,
AI revision envelope + validation, approvals list, verbatim
intervention (decision, rationale, embedded proposal copy,
`executed: false`). Derived on demand: calculations, reports, proposal
text via `select_proposal`. No execution records exist anywhere;
`executed` is always false by codec enforcement.

Finding: top-level snapshot `proposal` is always null in production
(`attach_proposal` is test-only). Proposal binding survives via the
verbatim `intervention.proposal` copy and deterministic re-derivation —
link verification must use those, not the null field.

## 3. Contract gap analysis (`docs/receipt-link-contract.md`)

Sound core: separate link record, explicit operator event, no
retroactive inference, append-only supersession, historical receipts
stay unlinked. Gaps: (a) assumes a populated top-level proposal
record (§2 above); (b) single event type `post-assessment-link`, no
taxonomy for audit-path or revision links; (c) no rejected/invalid
link state (only active/superseded); (d) no read-time verification
state in the record; (e) binds prediction hash but not the AI revision
identity; (f) no created-before-identity temporal rule (receipt
`created_at` vs run prediction `locked_at` ordering should be a
check, never identity). No second contract needed — amend V1.

## 4. Valid vs invalid linkage (decision table)

Valid: receipt loads; integrity passes; `case_id` matches;
investigation hash matches; prediction hash matches the run's locked
record; proposal/decision versions match the run's records (or a
recomputed `select_proposal`); explicit operator event with authority
recorded; snapshot revision referenced; created-after-lock ordering
holds. Invalid: historical unbound receipts; timestamp/text/case-name
matching alone; hash match without identity; cross-run association;
approval shown as execution; simulation receipt shown as customer
action; unverified claims; stale snapshot revision; unknown schema.
Minimum evidence for a verified link: exact run id + exact receipt id
+ verified source association + event/version binding + provenance +
authority + integrity metadata — all rechecked at read time.

## 5. Lifecycle consistency

Links live outside `receipt.json`: bytes, hashes, timestamps, provider
metadata, adjudications, and drift semantics untouched. Revocation =
append superseding record; originals never edited or deleted.

## 6. Security risks

Receipt-ID guessing (unguessable ids + no enumeration endpoint
required); cross-mission association (exact-match checks);
traversal (fixed registry paths, regex run ids); forged provenance
(recompute, never trust); leakage (registry outside served trees,
0600); replay/duplicates (one active link per run, CAS);
corrupt records (fail closed); unverifiable model content (validation
≠ truth). Single-user local model only; no tenant/auth/encryption
claims.

## 7. Minimum implementation design (MC-008.2 proposal, not built)

New `backend/link_registry.py` (atomic file registry, same durability
pattern as the snapshot store); explicit operator action wiring
(one endpoint or CLI, owner choice); verification reusing
`verify_receipt` + snapshot recompute + §4 table; failure codes
 mirroring pointer states; permission 0600; registry outside served
trees; rollback by supersession; ~40–60 new tests. Receipt creation,
mission flow, snapshots, and frontend unchanged except a read-only
linkage status line.

## 8. Test plan (Test H scenarios)

Covered now: identity match/mismatch foundations, version binding
source, missing provenance (null proposal field), historical unbound
receipts, integrity verification. MC-007.2/007.3 suites cover stale
snapshots, unknown schemas, CAS conflicts. Remaining for MC-008.2:
forged identity, duplicate link, approval-vs-execution, synthetic
classification — all against temp dirs with mock link records.

## 9. Owner decisions required

1. Link action surface: dedicated endpoint vs offline CLI.
2. Registry location/retention alongside `mission-snapshots/`.
3. Event taxonomy beyond `post-assessment-link`.
4. Whether AI-revision binding is required in V1.
5. Local repo initialization (still pending, no remote).

## 10. Recommendation

**CONDITIONAL GO for MC-008.2** — the contract is sound with the §3
amendments; historical receipts correctly stay unlinked; scope is
one small registry module plus wiring. Estimated complexity: low.
