# FDE Command Center

### TalonSight Technologies

**From uncertainty to evidence-backed engineering decisions.**

FDE Command Center 2 is an investigation platform combining source provenance, competing hypotheses, immutable diagnostic predictions, deterministic assessments, human decisions, and graphical evidence exploration.

## Demo

🎬 **[Watch the 3-Minute YouTube Demo](https://youtu.be/0wfe180H3VU)**

🌐 **Live Application:** Public deployment pending.

The application currently runs locally for synthetic demonstrations.

## Running Locally

```bash
cd ~/Documents/FDE-Command-Center-2

FDE2_PROFILE=dev \
FDE2_DATA_DIR=/tmp/fde2-safari \
python3 -m backend.server --port 18080
```

Then visit `http://127.0.0.1:18080/`.

The seven graphical investigation workspaces are available at `/visual.html`.

> Security notice: Synthetic demonstration data only. Not approved for real customer data or public network deployment.

## Developed by

TalonSight Technologies

AI-powered operational investigation assistant for Forward Deployed Engineers.
Helps explain why a business system fails to produce expected outcomes even
when the technical system looks healthy.

Independent project. No TalonSight code, books, or other applications are
used or imported. All seed data is fictional.

## Architecture (slice 1)

- `backend/` — pure-Python domain, stdlib only, in-memory:
  `workspace.py`, `truth_map.py`, `ledger.py`, `fixtures.py`, `model_client.py`
- `frontend/` — static shell (`index.html`, `app.js`), no build, no backend coupling yet
- `tests/` — stdlib `unittest` foundation suite

## Muse Spark 1.3 readiness

`backend/model_client.py` defines a `ModelClient` protocol plus
`NoOpModelClient`. A future Meta Model API client implements the same method
without touching domain code. No network calls in this slice.

## Run tests

python3 -m unittest discover -s tests -v

## Task 002 — source-verifiable Truth Map (case-001)

Fixtures: `fixtures/case-001/policy.md`, `dispatcher.md`, `manager.md`, `events.csv`. All fictional.

Disagreement: policy requires urgent assignment within 1h and acknowledgment
within 4h; dispatcher admits leaving urgent unassigned overnight; manager claims
no urgent ever waits and the dashboard shows 100% on-time. CSV data contradicts
both stakeholder claims (unassigned cases, late/missing acks).

Quotation verification (`backend/quotes.py`): exact substring match only,
case/punctuation/whitespace sensitive. Verified quotes carry doc_id plus start
and end offsets. Altered or invented quotes raise QuoteVerificationError.

Calculation rules (`backend/events.py`, deadline 4h wall-clock): eligible =
triage URGENT; assigned = assigned_at present; complete window =
window_close >= created + 4h; valid timely ack = ack present, ack >= created,
ack >= assigned when assigned, ack <= deadline. Incomplete = eligible without
valid timely ack and window closes before deadline (excluded from lacking).
Lacking = eligible minus within minus incomplete. Ordering anomalies flagged
and never counted as within. Expected: 7 eligible, 5 assigned, 1 within, 4
lacking (002, 003, 004, 008), 2 incomplete (005, 006).

Evidence layers (`backend/evidence.py`): policy_claim, stakeholder_report,
computed_behavior, interpretation. Irrelevant symptom: floor-2 printer jam is a
stakeholder report with causal_relevance=False and no CSV role.

Limitations: wall-clock 4h stands in for business hours; CSV timestamps assumed
well-formed ISO; first verbatim match wins for repeated quotes; no API calls.
Unsupported: root-cause verdict — hypotheses stay in the ledger as
interpretations, not findings.

## Task 003 — Evidence Inspection Workspace (case-001)

Strict categories (`backend/report_categories.py`, additive over Task 002):
eligible 7; with assignment timestamp 5; assigned within 1h 5 of 7
(rule assigned_at <= created + 1h); valid ack within 4h 1 of 7; confirmed
misses 3 (case-002, case-003, case-004 — complete window, no valid ack, no
anomaly); anomalous 1 (case-008, needs source check, never a confirmed miss);
incomplete 2 (case-005, case-006, insufficient evidence, never a confirmed
miss). Partition: 1 + 3 + 1 + 2 = 7.

Report data (`backend/report.py`) is backend-generated: verified quotations
with doc ids and offsets, calculations with denominators/rules/sources,
source-backed contradictions, unresolved questions, hypotheses labeled
unverified interpretations, printer note as reported observation only.

Build: `python3 -m backend.build_report` writes `frontend/case-001.json` and
`frontend/case-001.html` (self-contained, embedded backend data, no hardcoded
JS snapshot). Serve: `python3 -m http.server 8000` from the repo root, then
open http://localhost:8000/frontend/case-001.html in a browser.

## Task 004 — Muse Spark investigation (synthetic only)

Adapter (`backend/meta_adapter.py`): model `muse-spark-1.3`, Standard mode
only, stdlib urllib, no SDK. Official Responses API: POST
`https://api.meta.ai/v1/responses` with `{"model", "input"}`; assistant text
is extracted from the output message content blocks. Credentials server-side
via `MODEL_API_KEY` (primary, `META_API_KEY` still accepted) and
`META_MODEL_ENDPOINT` (optional override); missing key raises
`MissingCredentialsError` before any network use. `MockAdapter` serves tests
and offline use with no network. No Contributor model IDs.

Investigation (`backend/investigation.py`): context is built only from
verified quotations and deterministic calculations in the existing report.
Structured output requires observations (with basis + refs), competing
hypotheses, unresolved questions, diagnostic experiments, a provisional
recommendation (human approval required, no production execution), and
counter-evidence. Every ref is validated against the backend registry;
unknown refs, metric mismatches, stakeholder reports posed as verified
behavior, model-claimed validated conclusions, and printer-as-cause are all
rejected. Model text is parsed as JSON only, never executed.

Offline use: `produce_investigation(MockAdapter(), ".")` returns a validated
mock investigation. Live Meta integration is NOT demonstrated: no authorized
request has been made from this environment, so no live claim is made.

API usage: one POST per investigation to `https://api.meta.ai/v1/responses`
with `{"model": "muse-spark-1.3", "input": <instructions + verified context>}`.
Live smoke test (explicit only, one minimal request): `python3 -m backend.smoke_test`
with `MODEL_API_KEY` set; exits 2 without credentials and never prints the key.

## Task 005 — AI Investigation Workspace

Server (`backend/server.py`): serves `frontend/` plus JSON endpoints.
`GET /api/report` returns the verified case-001 report. `GET
/api/investigation?mode=mock` returns a deterministic offline investigation
(no model call, for UI testing). `POST /api/investigation {"mode": "live"}`
runs the explicit live pipeline through `muse-spark-1.3` Standard; without a
key it returns 503 and sends nothing. `POST /api/approval
{"decision": "approve"|"reject"}` records the human decision in memory and
always reports `executed: false` — no production change can run.

Page (`frontend/investigate.html` + `investigate.js`): offline-mock and live
buttons, validated sections with evidence refs, hypotheses tagged unverified,
approval controls, safe provider-error display. No secrets or findings are
hardcoded in the frontend.

Launch: `python3 -m backend.server --port 8000` from the repo root (not
currently running), then open http://localhost:8000/investigate.html in a
browser. Mock mode needs no key; live runs only on its button press.

## Task 005.1 — live-rejection diagnosis

Root cause: the old model prompt never taught the schema the validator
enforces (observation `basis`, allowed reference IDs, approval flags, exact
metric labels). Realistic model output therefore fails first at
`observations[0]` — typically `unknown-reference` (guessed IDs like
`policy.md`) or `missing-field` (`basis`). Responsibility lies with the
application contract, not the model output.

Fix (`backend/investigation.py`): `build_instructions(registry)` generates the
prompt from the same constants and registry the validator enforces, so the
two cannot drift. Rejections raise `DiagnosticError` with stage, category,
field path, and rejected ref. The server attaches a per-request correlation
ID, records the last 20 diagnostics in memory, returns them on the 502
(`GET /api/diagnostics/latest` replays the latest), and never exposes model
text, prompts, or credentials. Verification rules are unchanged and no paid
request is ever retried. Live resolution is NOT claimed: it needs a new,
explicitly authorized live run against the strengthened prompt.

## Task 006 — locked-prediction experiment (EXP-001)

Experiment (`backend/experiment.py`): discriminates queue-handling assignment
delays (H-QUEUE) from an acknowledgment bottleneck or reporting problem
(H-ACK) via a source-log check for case-003. The outcome was authored once at
implementation time, before any prediction existed. Lifecycle: proposed →
prediction locked → result revealed → assessed. Predictions carry hypothesis
ID, procedure, expected observation, criteria, evidence refs, version `v1`,
server timestamp, and a SHA-256 change-detection hash (not tamperproof).
Reveal before lock, prediction edits, and out-of-order transitions are
rejected. Assessment is deterministic: matching findings record `supported`,
mismatches `contradicted`, with refs. The outcome is server-side only and
appears solely in the authorized reveal response.

Demo: `python3 -m backend.server --port 8000` (not currently running), open
http://localhost:8000/investigate.html, scroll to the experiment panel:
lock a prediction (note the hash), reveal the result, then assess. A fresh
session shows `withheld` with no outcome.

Security scope (honest): secrecy holds only while the outcome stays out of
served responses and files, which the disclosure tests enforce. The hash aids
demo change-detection; it is not a tamperproof seal and there is no audit log.

## Task 007 — AI prediction, revision, and learning

Engine (`backend/ai_prediction.py`): AI predictions use only pre-reveal
evidence (verified quotes, computed metrics, H-QUEUE/H-ACK, procedure); the
outcome and its markers never enter prediction context, instructions,
responses, or static files. Structured prediction requires hypothesis ID,
expected finding, observation, procedure, criteria, refs, uncertainty, and
alternatives, validated against the registry. Revisions after reveal must
cite the new evidence, restate the deterministic comparison honestly, keep
alternatives and counter-evidence, and never declare a verified root cause.
A match is support, never proof. Because outcome and code share this repo,
runs are labeled demonstration-only, not genuine blind evaluations.

Endpoints: `POST /api/prediction/generate {mode}` (mock needs no key; live
needs `MODEL_API_KEY`, nothing automatic), `POST /api/prediction/lock
{confirmed: true}` (explicit human confirmation; AI locks carry origin,
model ID, version `v2`, evidence cutoff, timestamp, hash),
`POST /api/revision/generate {mode}` (needs assessed state; revision stored
as a new version, originals preserved), `POST /api/revision/approve`
(human-reviewed revision tag; never executes anything; no causal validation performed).

Demo: launch the server, open the investigation page, Generate (mock) →
review → confirm → Lock → Reveal → Assess → Revise (mock) → compare
Before/After → Approve. No live Meta API request occurred in this build.

## Task 007.1 — prediction fidelity and evidence-based revision

Fidelity fix: locking used to narrow the reviewed prediction (dropping
procedure, uncertainty, alternatives, metrics, and trimming text). The locked
record now preserves every reviewed field verbatim, and the review pane shows
the full text that locking preserves. Regression-tested field by field.

Revision schema now requires original prediction plus deterministic
assessment, new evidence citing the reveal, per-hypothesis effects for H-ACK
and H-QUEUE with reasons, remaining alternatives, unresolved questions, a
next test with expected observations, a provisional recommendation, and
reversal evidence. Stances stay at supported/contradicted/unresolved; effect
stances must agree with the deterministic result for the predicted
hypothesis; verified-root-cause language is rejected. A match remains support,
never proof, and the UI term is now "human-reviewed revision" with an
explicit no-causal-validation note.

Browser verification (manual): start `python3 -m backend.server --port 8000`,
open http://localhost:8000/investigate.html, run Generate (mock) and confirm
the review shows procedure, criteria, uncertainty, alternatives, and metrics;
tick confirm, Lock, and check the experiment panel repeats the same text with
a hash; Reveal, Assess, Revise (mock), and confirm Before/After compares
H-ACK vs H-QUEUE effects with reasons.

## Task 007.2 — evidence scope and audit display

Scope correction: the old revision marked H-QUEUE contradicted from
case-003 alone. Every revised hypothesis effect must now declare scope
(`single-case` or `population`); population scope needs events.csv plus two
distinct cases, and contradicting a hypothesis needs population scope — one
case can support a narrow finding but never disprove the wider hypothesis.
EXP-001 now reads H-ACK supported (single case-003 feed gap), H-QUEUE
unresolved across the population, with no organization-wide root cause. The
locked-prediction panel renders every reviewed field (finding, observation,
procedure, criteria, uncertainty, alternatives, refs, metrics, model,
timestamps, version, hash), and tests assert wholesale reviewed-to-locked
equality. Manual browser check: after Revise (mock), confirm the comparison
shows scope tags per hypothesis and the no-org-cause line.

## Task 008 — private six-case comparative evaluation

Cases (`eval/cases/EVAL-01..06`): ownership gap, stale data, definition
conflict, tool bypass, permission failure, genuine technical failure. Each
has a fictional policy, two stakeholder accounts, an event CSV, an outcome,
competing explanations, a misleading signal, a cutoff, and a hashed manifest
(`python3 eval/freeze.py` regenerates them).

Separation: public evidence in `eval/`; gold keys, rationales, and results
in `evaluator-private/` (gitignored, never served, never in prompts); results
under `evaluator-private/results/`. This is evaluation separation, not a
secure blind environment, since local files remain developer-readable.

Harness (`backend/eval_harness.py`): manifest verification, deterministic
stats, neutral baseline prompt vs verified FDE context over identical
evidence, structured validation, auto scoring of causal language (M2) and
citation validity (M3) with M1/M4/M5/M6 as pending human inputs, and a
zero-network fixture mode. Rubric frozen as `v1-frozen` in `eval/rubric.md`.

Live runs only via `python3 -m backend.eval_live --approve-live
[--max-requests 12]`, which prints its plan (requests, model
`muse-spark-1.3` Standard, unknown spend with a request-count ceiling, stop
conditions, storage) and stops at the ceiling. No live call occurred in this
build; fixture reports are demonstrations, never measured performance.

## Task 008.1 — benchmark integrity audit and pilot readiness

Integrity findings: v1 gold positions were imbalanced (all at a single
position), so public hypothesis ordering revealed the answer position; no
other leakage was found (prompts, contexts, templates, bundles, and served
paths hold no gold text; both conditions receive identical evidence and
cutoffs). v1 is archived frozen (`eval/FROZEN_v1.md`); v2 (`eval-v2/`,
manifest with base `v1`) reorders only `explanations.md` with gold positions
balanced in aggregate 2-2-2 and unchanged gold contents. Scoring limits:
auto scores cover reference resolution — not semantic support — plus
causal-language flags; M1/M4/M5/M6 need a human via
`eval/worksheet-template.md`, which allows `unresolved` verdicts and keeps
rejections at 0. Limitation: cases were authored alongside the
implementation, so v2 fixes position only, not authorship independence.

## Task 008.1a — answer-key isolation and pilot safety gate

A follow-up audit found correct-answer mappings inside distributable assets:
the label mapping in `eval/freeze.py`, the positions field in the v2
manifest, and answer columns in the v2 README. All mappings and key-derivation
logic moved to `evaluator-private/` (gitignored); the v2 manifest was
revised to r2 with the positions field removed (history in
`eval-v2/MANIFEST_HISTORY.md`, old and new hashes recorded); public docs now
report balance in aggregate counts only. Gold loading sits behind
`backend/eval_private.py`, absent from the package root and never imported
by prompt builders. The live command runs a leakage preflight first and
refuses on any finding. No live calls occurred; the four-request pilot stays
ready but unexecuted.

Pilot (not executed): `python3 -m backend.eval_live --pilot --approve-live`
runs EVAL-02 and EVAL-06 under a strict four-request ceiling on v2, saving
raw responses plus the manifest for independent review. No live calls
occurred during implementation; no superiority claim is made without
measured, independently reviewed results.

## Task 008.4 — confirmed adjudication and main-run readiness

Confirmed record (`evaluator-private/adjudications/confirmed-pilot-0084.json`,
owner-confirmed via user instruction, no signature claimed): EVAL-02
baseline M2=1, EVAL-06 baseline M1=2, both baselines M3=2. Totals baseline
23/24, FDE 24/24, with an explicit no-superiority statement. Originals
untouched.

Main run (not executed): `python3 -m backend.eval_live --main-run
--approve-live` targets EVAL-01/03/04/05 on v2 r2 under a strict
eight-request ceiling, with preflight, failure recording without
substitution, unknown spend, and private storage. Blank worksheets await at
`evaluator-private/adjudications/pending-main-run.md`. No model calls
occurred in this task.
