# MC-007.1 — Durable Mission Persistence Architecture Audit

Status: AUDIT ONLY. Persistence is not activated. No production code was
changed in this milestone. Only this document was added.

Baseline: `python3 -m unittest discover -s tests` → 563 tests, OK,
1 pre-existing real-socket skip (sandbox has no listening sockets).

## 1. Inspected files and verified contracts

- `docs/mission-persistence-contract.md` — MissionSnapshotV1 design (§1–§11). Accurate as design; three drifts vs implementation noted in §4.
- `docs/receipt-link-contract.md` — MissionReceiptLinkV1 requires an explicit operator-owned link event, a separate link registry, and no case-ID-only or retroactive linking. None of that machinery exists yet, which is the correct deferred state.
- `backend/mission_snapshot.py` — production codec: `build_snapshot`, `attach_proposal`, `encode_snapshot`, `decode_snapshot`, `verify_against_live`, `derive_stage`. Pure functions, no I/O. Digest-then-schema validation order; stage re-derived on load, never trusted.
- `backend/mission_store.py` — atomic store: `commit_snapshot` (validate → compare-and-swap on revision → temp write + fsync → `os.replace` → dir fsync → confirm by reload), `load_snapshot` (never falls back to `.prev`), `inspect_snapshot_status` (`ok` / `missing` / `recovery-required`, no contents leaked). 0700 dirs, 0600 files, `flock` sidecar lock, per-run files `mission-<run>.json`.
- `backend/mission.py` — transitions: `choose_diagnostic` (once, `already-chosen`), `decide_intervention` (once, `already-decided`, proposal id/version binding, `executed` never true), `select_proposal` (deterministic from diagnostic+assessment+outcome), `mission_report` (derived, 13 sections).
- `backend/experiment.py` — `lock_prediction` (`already-locked`), `reveal_outcome` (requires lock, `too-early` otherwise), `assess` (deterministic). State also carries `revision` / `revision_validation` (AI revision workflow).
- `backend/server.py` — one in-memory context from `new_context()` installed at startup (`Handler.context`), loopback bind `127.0.0.1`, chaos endpoint loopback/Origin/Host gated. No snapshot/store import; store remains unwired (re-verified).
- `tests/artifacts/mc-006-acceptance.json` — all 18 recorded SHA-256 hashes recomputed and match. MC-006 history intact.

## 2. Source-control finding

The workspace is not a Git repository because no `.git` directory was ever created here (a `.gitignore` exists but no repo was initialized). Per the milestone restriction no repo was initialized and nothing was pushed. Consequence: revision identity still rests on artifact hashes, as in MC-006. Recommendation: initializing a local repo (no remote) remains an owner decision, ideally before MC-007.2 writes durable state worth versioning.

## 3. Authoritative state ownership matrix

| State | Owner / location | Kind | In snapshot? | Sensitivity / side effects |
|---|---|---|---|---|
| `mission_run_id` (mr-…) | server-minted uuid4, `mission.py:152` | authoritative, immutable | yes (identity root) | none to restore |
| mission/case/experiment ids | code constants | fixed | yes (pinned) | mismatch → reject |
| fixture files | `fixtures/case-001/*` | synthetic source | no (manifest digest only) | drift → quarantine, never silent recompute |
| calculations, quotes, contradictions, reports | recomputed per view | derived | no | none |
| `mission.diagnostic`, `audit_viewed` | operator via `choose_diagnostic` | lifecycle, once | yes | none |
| `experiment.prediction` + hash | `lock_prediction` | immutable after lock | yes, verbatim, hash re-checked | rewriting breaks digest |
| `experiment.outcome` | `reveal_outcome` | concealed, once | yes | restore must not re-expose beyond existing stage gates |
| `experiment.assessment` | `assess`, deterministic | derived-from-inputs | yes (inputs + result, so recovery re-verifies) | never auto-recomputed on load |
| `experiment.revision`, `revision_validation` | AI revision workflow | lifecycle record | **NO — GAP, see §4.1** | restore drops approved AI revision from report |
| `ctx["approvals"]` (AI-investigation decisions) | `server.py:488` | lifecycle record | **NO — GAP, see §4.1** | restore drops AI approval history |
| proposal id/version | `select_proposal`, deterministic | derived pointer | yes (id+version; text recomputed) | recompute must agree or fail |
| `mission.intervention` + rationale | `decide_intervention` | immutable, version-bound | yes, verbatim | `executed` must stay false |
| `ctx["diagnostics"]` rolling log | server observability cache | temporary | no (by design) | none |
| chaos fixtures/results/eval/recovery | chaos modules + static artifacts | synthetic, independent | no | never part of mission runs |
| receipts, links | `evaluator-private/`, future registry | historical | no | no linkage inferred, ever |
| frontend filter/selection/view state | browser only | temporary | no | none |

## 4. Contract assessment — three drifts (all fail-closed, none blocking audit)

1. **Revision/approval records not persisted (real gap).** Contract §1 row 10 marks `experiment.revision*` "Yes (record, not recompute)", but `build_snapshot` stores only prediction/outcome/assessment, and `ctx["approvals"]` is stored nowhere. Verified live: `"revision" in body == False`. A restored run would lose an approved AI revision and AI approval history while the mission report derives sections from them. Smallest fix (MC-007.2): extend the codec body with verbatim `revision`/`revision_validation`/`approvals` plus validators, or explicitly scope snapshots to the Field Mission and document the AI-workflow exclusion. Do not silently accept the loss.
2. **`.prev` fallback wording.** Contract §4.3 contemplates verified-`.prev` fallback; `load_snapshot` never falls back and `inspect_snapshot_status` never consults `.prev` — strictly more fail-closed than the text. Keep the code; correct the sentence in MC-007.2.
3. **Retry semantics.** Contract §4.5 suggests a retried identical decision returns the existing record; the code (correctly) raises `already-decided` and writes nothing. Preserve the code; correct the sentence. Rejected requests must keep writing nothing.

## 5. Security and failure-mode assessment (Task C, verified offline in temp dir)

Identity: `RUN_RE` enforced at codec, store path builder, and status check (`bad-identity` otherwise); run id is a path stem, never a directory — traversal has no carrier. Writes: same-directory temp + fsync + `os.replace` + dir fsync + confirm-reload; stale writers abort (`stale-revision`), non-monotonic bodies abort (`bad-revision`); corrupt main → `('recovery-required', 'corrupt')`, missing → `('missing', 'no-snapshot')`; malformed/unknown-schema → codec rejection (digest checked first, then `bad-schema`). Repeat submissions are once-only rejections, never duplicates or overwrites. No network, no model, no receipt, no execution path exists in either module. Adequate for the bounded single-user local demo; explicitly not production auth, tenant isolation, or encryption — unchanged claim, still blocking production use.

## 6. Restoration contract (maps to actual codes)

Valid → load with id/stage/locks/decision intact. Missing → fresh run, new id. Corrupt/bad digest/unknown schema/missing fields → `recovery-required` + operator archival; never auto-fresh, never auto-fill, never auto-upgrade. Wrong-mission file → `bad-identity` mismatch. Stale submit → `stale-revision` abort. Conflicting files → operator selects, loser archived (no chooser exists yet — see §8.3). Mid-save crash → temp discarded, main intact; post-replace failure → explicit `confirm-failed`, never reported success. Restart after save → exact run resumes, outcome still gated by existing `public_view`; restart after interrupt → temp ignored. Restoration performs zero transitions: no rewrite, no reveal, no reassess, no execute, no simulation, no link, no provider call — there is simply no code path from load to any of them.

## 7. Minimal integration plan (MC-007.2 proposal, not implemented)

1. `backend/mission_snapshot.py`: add verbatim revision/approval fields + validators (closes §4.1) or document the exclusion.
2. `backend/server.py` only: after each accepted mission transition, `build_snapshot` (revision = committed+1) → `commit_snapshot` to a non-served dir (new `mission-snapshots/`, gitignored); rejected requests write nothing. At startup: `inspect_snapshot_status` on the active-run pointer → load or fail closed with an operator message.
3. New pointer file (e.g. `active-run.json`) recording which run is live — the one piece the current design lacks (§8.3).
4. No new routes, no new methods, no receipt/link work, no model changes. Backward compatible: no snapshot on disk → fresh run, exactly today.
5. Tests: §5 decision-table matrix against temp dirs (already the store suite's shape) + wiring tests proving rejected transitions write nothing and restart restores lock/concealment/binding.

## 8. Unresolved decisions (owner)

1. §4.1 scope: persist AI revision/approvals in the snapshot, or scope snapshots to Field Mission only?
2. Store directory name/location + retention/deletion rule for completed runs.
3. Active-run pointer format and conflicting-files selection procedure.
4. Local repo initialization (no remote) before durable state exists.
5. Operator recovery procedure wording for `recovery-required` states.

## 9. Recommendation

**CONDITIONAL GO for MC-007.2** — codec and store are sound and their failure semantics were re-verified live; integration may proceed once the owner resolves §8.1–§8.3. No new tests were added in this audit (existing codec/store suites already cover the exercised semantics; scratch verification used temp dirs only, never workspace state).
