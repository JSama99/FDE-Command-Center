# MissionSnapshotV1 — Durable Mission State Contract (MC-004d)

Status: DESIGN AND OFFLINE VALIDATION. No runtime persistence,
migration, endpoint, or recovery control was implemented in MC-004d.
Test-local reference code lives in `tests/test_mission_snapshot.py`
and is not shipped behavior.

## 1. Current state inventory (verified against code)

All mission authority lives in one in-memory dict built by
`new_context()` (`backend/server.py:87`) and installed once at startup
(`Handler.context = new_context()`, `backend/server.py:517`).

| # | Field | Origin | Mutated by | Persist? |
|---|---|---|---|---|
| 1 | Fixture files `fixtures/case-001/*` | Authored synthetic data | Nothing at runtime | No — pinned by manifest digest |
| 2 | Deterministic calculations, quotes, contradictions | `build_case_report()` recomputed per view | Never stored | No — recompute from pinned fixtures |
| 3 | `mission.mission_run_id` | Server-minted `uuid4` at `new_mission_state()` (`backend/mission.py:152`) | Never (invariant, MC-004c) | **Yes — identity root** |
| 4 | `mission.diagnostic` | Operator via `choose_diagnostic()` (`:230`), once, feed-probe or timestamp-audit | Once; rewrite rejected (`already-chosen`) | Yes |
| 5 | `mission.audit_viewed` | `diagnostic_result()` (`:242`) timestamp-audit path | Once, False→True | Yes |
| 6 | `experiment.status` | `proposed → prediction locked → result revealed → assessed` via `lock_prediction` / `reveal_outcome` / `assess` (`backend/experiment.py`) | Gated transitions only | Yes |
| 7 | `experiment.prediction` (record + `hash`) | `lock_prediction()`; immutable afterwards (`already-locked`) | Never after lock | **Yes — verbatim, hash-checked** |
| 8 | `experiment.outcome` | `reveal_outcome()`; requires locked prediction (`too-early` otherwise) | Once | **Yes — concealed payload** |
| 9 | `experiment.assessment` | `assess()`; deterministic compare | Once | Yes |
| 10 | `experiment.revision*` | AI-revision workflow (`backend/server.py:331,383`) | Gated | Yes (record, not recompute) |
| 11 | Proposal id/version | `select_proposal()` derives from diagnostic+assessment+outcome (`:274`) | Derived, deterministic | Store id+version; spec text recomputed from code constants |
| 12 | `mission.intervention` (`decision/note/proposal/at/executed`) | `decide_intervention()` (`:334`); rationale + version binding enforced | Once (`already-decided`) | **Yes — verbatim, incl. rationale** |
| 13 | Reports (`mission_report`, 13 sections) | Derived from state + fixtures (`:480`) | Never stored | No — regenerate |
| 14 | `ctx["diagnostics"]` rolling log (`server.py:97`) | `_record_diagnostics`, capped at 20, investigation subsystem | Append-only | No — observability cache, not mission authority |
| 15 | Frontend FILTER/QUERY/SELECTED/view toggles | Browser only | Browser only | No |

Rule: persist lifecycle facts (3–12); recompute everything derivable
from pinned fixtures + code constants (2, 11-spec, 13). Never persist a
derived conclusion as an independent fact without its validation
dependencies — the snapshot stores assessment *inputs* (prediction
hash, outcome finding) alongside the result so recovery re-verifies
rather than trusts.

## 2. MissionSnapshotV1 schema (proposed)

```json
{
  "schema": "MissionSnapshotV1",
  "snapshot_revision": 7,
  "saved_at_utc": "<iso-8601>",
  "mission_run_id": "mr-...",
  "mission_id": "mission-case-001",
  "case_id": "case-001",
  "experiment_id": "EXP-001",
  "lifecycle_stage": "assessed",
  "mission": {"diagnostic": "feed-probe", "audit_viewed": false},
  "prediction": {<verbatim locked record incl. hash>},
  "outcome": {<verbatim revealed outcome>} | null,
  "assessment": {<result, reason, refs>} | null,
  "proposal": {"proposal_id": "PROP-002", "version": "v1"} | null,
  "intervention": {<verbatim decision record>} | null,
  "source_manifest": {"fixtures/case-001/events.csv": "sha256…", …},
  "snapshot_sha256": "<over all fields above>"
}
```

`lifecycle_stage` is derived at save time from the same gates as
`stage_status()` and re-derived on load — never trusted from disk.
`source_manifest` uses `receipt.evidence_manifest()` so fixture drift is
detectable. `snapshot_sha256` covers every other field (canonical JSON).

## 3. Mechanism: atomic file snapshots (selected)

Comparison for this local single-process project, stdlib only:

- **Atomic file snapshot**: write temp file in same directory,
  `flush()` + `os.fsync()`, `os.replace()` over `mission-<run>.json`.
  Crash during write leaves either the old or the new complete file —
  never a partial authoritative state. Locking via `fcntl.flock`
  (stdlib, POSIX) for concurrent writers. Corruption recovery = keep
  previous generation (`mission-<run>.json.prev`). No new dependency.
- **SQLite transactions**: stronger concurrent story and queryability,
  but adds schema/migration machinery disproportionate to one dict.

Selected: atomic file snapshots, one file per run id plus `.prev`
generation, `0600` permissions, inside a non-served directory. fsync
before replace; smeared-timestamp risk accepted for the demo and
documented (see §9).

## 4. Atomic transition rules (proposed)

1. Every accepted state-changing transition commits exactly one new
   snapshot with `snapshot_revision = previous + 1` (monotonic,
   gapless per run; a retry replays the same transition idempotently
   and must not mint a second revision for one human decision).
2. A rejected request (`already-chosen`, `too-early`, `already-locked`,
   `already-decided`, `proposal-mismatch`, bad payload) writes nothing:
   revision, file bytes, and `.prev` are untouched.
3. Partial writes never become authoritative: readers load the file,
   verify `snapshot_sha256` over canonical bytes, and fall back to
   `.prev` only if `.prev` itself verifies — otherwise fail closed.
4. Concurrent writers serialize on an `flock`'d sidecar lock; a writer
   holding a stale revision aborts instead of overwriting (compare the
   on-disk revision before replace).
5. Idempotency keys: human decisions and diagnostic transitions carry
   the client-visible preconditions (e.g. expected revision); a retried
   identical decision returns the existing record, never a duplicate.
6. Proposal/decision binding and prediction immutability are rechecked
   at commit time, not only at request time: the committer reloads the
   authoritative record and re-runs `select_proposal` /
   hash-comparison before writing.
7. Reveal ordering is structural: a snapshot containing `outcome` must
   contain a locked `prediction`; loaders reject outcome-without-lock.

## 5. Startup recovery decision table (proposed)

| # | Condition | Recovery |
|---|---|---|
| 1 | No saved state | Start a fresh run with a new `mission_run_id` |
| 2 | Valid current snapshot | Load it; run id, stage, locks, decision intact |
| 3 | Missing required fields | Reject; explicit operator recovery, never auto-fill |
| 4 | Unknown schema version | Reject; operator migrates or archives, never auto-upgrade |
| 5 | Corrupted bytes / bad digest | Reject; try verified `.prev`, else operator recovery |
| 6 | Source-manifest drift | Load run identity but quarantine derived views; recompute blocked until fixtures pinned; operator decides |
| 7 | Interrupted write (temp file present, main intact) | Discard temp, load main |
| 8 | Duplicate/conflicting run records | Refuse to choose; operator selects, loser archived |
| 9 | Stale revision presented by a writer | Abort the write, keep authoritative revision |
| 10 | Previously completed mission | Load read-only-complete; further transitions rejected except explicit new run |
| 11 | Locked-but-unrevealed mission | Resume awaiting reveal; outcome stays concealed |
| 12 | Unauthorized/malformed decision record | Reject record; run continues without a decision |

Fail-closed always: any doubt about integrity or stage-gating means no
mission is presented as trustworthy. There is deliberately **no**
"reset to fresh" path for invalid state — only explicit operator
archival followed by a new run with a new id.

## 6. Confidentiality and access boundary (proposed)

- Store: non-served directory (same exclusion posture as
  `evaluator-private/`), `0700` dirs, `0600` files, operator-owned.
- The snapshot contains the concealed `outcome` and human rationales:
  readable only by the server process. Frontend responses must pass
  through the existing stage gates (`public_view`, reveal-gating) —
  never serialize the snapshot to the browser.
- Retention: completed runs retained for audit until explicit operator
  deletion; deletion removes current + `.prev` + temp files. No backup
  copies customer data off-host in this design.
- Integrity hash ≠ encryption: stated plainly. No multi-user auth,
  tenant isolation, or customer-grade access control exists; their
  absence blocks production use. No claim otherwise may ship.

## 7. Relationship to MissionReceiptLinkV1

Durable snapshots supply what linkage needs: stable run identity
across legitimate recovery (§5 rows 2/10/11), exact prediction bytes
for `prediction_sha256`, and the assessment/proposal versions a link
references. Still required separately and NOT authorized here: the
explicit link event, the link registry, and any receipt endpoint. No
case-ID-only linking, no retroactive attribution, no receipt mutation.

## 8. Migration and backward compatibility

- In-memory-only runs (everything before implementation) simply have
  no snapshot: startup finds no saved state (row 1) and starts fresh.
  Nothing migrates because nothing durable exists.
- Schema changes mean a new `MissionSnapshotV<n>`; old files stay
  readable by version dispatch, never silently upgraded.
- Fixture changes alter `source_manifest` → row 6 quarantine, never
  silent recomputation over new evidence.

## 9. Threat model and failure scenarios

Power loss mid-write (temp+replace covers), disk-full on replace
(commit fails, old file intact — must be surfaced, not swallowed),
clock skew (timestamps informational only; ordering comes from
revision), lock-holder crash (flock releases on close; stale temp
discarded per row 7), operator reads snapshot file directly (perms +
non-served dir; contents still sensitive — documented, not solved),
fixture swap under a live run (manifest quarantine), snapshot copied
to another host (run id collides conceptually — ids are random, not
host-bound; documented limitation), replayed decision POST (idempotency
preconditions), outcome scraped from snapshot file by local user
(out of scope for file-permission model; production needs encryption
and auth — explicitly absent).

## 10. Acceptance criteria

The server restarts into the exact run — same id, same stage, locked
prediction byte-identical, outcome still concealed pre-reveal,
decision bound to proposal version — while corrupted, unknown-version,
drifted, conflicting, or unauthorized states refuse to load and say so.

## 11. Smallest recommended implementation step (requires owner approval)

Snapshot codec + atomic writer/loader as pure functions
(`snapshot_bytes(state)`, `commit_snapshot()`, `load_snapshot()`)
with the §5 table as unit tests, wired to transitions only after the
codec round-trips offline. No endpoint, migration, or recovery-control
work until then.

## 12. Amendment MC-007.2 — revision records and active-run pointer

Offline hardening only. `backend/server.py` unchanged; persistence
remains disconnected.

### 12.1 Codec extension (implemented, `backend/mission_snapshot.py`)

The body gains three required nullable keys: `revision` (verbatim AI
revision envelope: origin, model_id, version ≥ 1, generated_at,
demonstration_only, revision content), `revision_validation`
(approve/reject record, `executed` false), `approvals` (list of
approve/reject records, each `executed` false). Validation is
structural plus binding: a stored revision must match the locked
prediction (hypothesis + expected finding) and restate the recorded
assessment result; a validation without a revision, a revision without
prediction + assessment, and any record with `executed` true are
rejected. Bodies predating this extension are rejected as
`bad-schema`. No durable snapshots predate it (the store was never
wired), so no migration exists. Schema name stays MissionSnapshotV1:
a compatible extension under fail-closed version handling.

### 12.2 Active-run pointer (implemented, `backend/active_run.py`)

Standalone offline module, never imported by the server. Record
`ActiveRunPointerV1` names exact `mission_run_id` + committed
`snapshot_revision` + monotonic `pointer_revision`. Fixed filename
`active-run.json` in the store dir (no browser-supplied paths;
symlink pointers refused; run id regex-enforced). `write_pointer`
loads the snapshot first and refuses uncommitted selections; optional
`expected_pointer_revision` gives compare-and-swap (stale writers
abort, newer selection preserved). `resolve_active` restores only the
selected generation; `load_committed` exposes explicitly-unpointed
generations for operator review. Store default directory name:
`mission-snapshots/` at the project root (gitignored), configurable
by passing an explicit directory — functions never use the default
implicitly. No automatic deletion in MC-007. Permissions 0700/0600
where supported; hash is integrity, not encryption; no tenant
isolation claimed.

### 12.3 Commit point and crash table

Commit point of a persisted transition = pointer replacement, ordered
after snapshot commit. Simulated-crash outcomes (deterministic fault
injection in temp dirs; not physical power-loss testing):

| # | Case | Outcome |
|---|---|---|
| 1 | Crash before snapshot write | Automatic: no files, fresh start |
| 2 | Crash during temp snapshot write | Automatic: temp ignored, fresh start |
| 3 | Crash after replace, before pointer update | Automatic: pointer honored from verified `.prev`, newer generation flagged `quarantined`, never restored |
| 4 | Crash during pointer update | Automatic if old pointer intact; else `pointer-corrupt`, operator recovery, snapshots untouched |
| 5 | Crash after pointer replacement | Automatic: new state authoritative |
| 6 | Snapshot corruption | `snapshot-invalid`, operator recovery (`.prev` available for manual inspection only) |
| 7 | Pointer corruption | `pointer-corrupt`, operator recovery, snapshots untouched |
| 8 | Missing snapshot | `no-snapshot`, fresh start |
| 9 | Unsupported version | `unsupported-pointer` / codec rejection, operator recovery |
| 10 | Stale revision | Write-time abort (`stale-revision` / `stale-pointer` / `revision-mismatch`); previous state preserved |
| 11 | Concurrent updates | CAS on snapshot revision and pointer revision; loser aborts |
| 12 | Valid snapshots, no pointer | `load_committed` returns `unpointed`; operator re-points explicitly |

A newer snapshot is never authoritative for being newer; only the
pointer-selected verified generation restores.

### 12.4 Operator language

`pointer_state_message()` maps every code to plain language:
no saved mission → "No saved mission found…"; save conflicts →
"Save failed; previous accepted state preserved…"; all integrity,
mismatch, and version failures → "Recovery required: …" naming the
cause. A recovery-required state is never labeled a restoration.

### 12.5 MC-007.3 integration proposal (not authorized yet)

After each accepted mission transition: build (revision =
committed + 1) → `commit_snapshot` → `write_pointer`; rejected
requests write nothing. At startup: resolve pointer or fail closed
with the §12.4 message. No new routes or methods. Supersedes §11.

### 12.6 MC-007.3 implementation record

Implemented as proposed, in `backend/persistence.py` (bridge) with
narrow wiring in `backend/server.py` (durable dispatch, startup boot).
Durable routes: the nine mission POSTs plus GET
`/api/mission/diagnostic/result` (timestamp-audit flip). Drafts
(`pending_ai`), diagnostics-only writes, and chaos execution never
commit. Transitions run on an isolated deep copy; only pointer
replacement acks durability. Pointer-after-commit failure →
degraded mode (reads continue, mutations 503) with restart adopting
the proven successor or aborting. Persistence engages only for
contexts carrying `_store_dir` (booted server); plain
`new_context()` keeps exact legacy behavior. Store location:
`FDE_MISSION_STORE` or `mission-snapshots/` (gitignored, never
statically served).

### 12.7 CP-002 operations record

Audit: metadata-only JSONL (`audit.log`, 0600) appended after each
durable accept/reject/failure plus boot; never bodies, rationales, or
secrets. A failed audit write after a committed transition returns the
truthful 200 but forces degraded mode (mutations 503) until restart;
reject-path audit failures go to stderr and never break the rejection.
Backup: `backend/backup.py` copies snapshot generations, pointer, and
audit log with a hash manifest, verifies pointer stability across the
copy, and restores only into empty directories after re-verification.
No replay, no overwrite, no cloud.

