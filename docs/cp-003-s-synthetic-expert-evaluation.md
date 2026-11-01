# CP-003.2-S — Synthetic Expert Evaluation (AI-SIMULATED)

Every judgment below is AI-SIMULATED. No real participants were
interviewed, observed, or scored. Nothing here populates CP-003
scorecards or moves the customer-validation GO / ITERATE / NO-GO
gate. Evidence base: `frontend/control.html/.js`, `mission.html`,
`backend/ai_prediction.py`, `mission.py`, `mission_snapshot.py`,
chaos/eval/recovery modules, case-001 fixtures, and the 660-test
suite (all passing).

## Phase 1 — Baseline inventory (verified behaviors)

Implemented: evidence ledger with classification + provenance;
H-ACK/H-QUEUE comparison with uncertainty preserved; locked
predictions with authorized reveal; deterministic assessment that
cannot declare a verified root cause (validator rejects the phrase —
`ai_prediction.py:43,237`); proposal version binding with human
rationale; Chaos Lab evaluation dashboard with counts over
denominators; recovery records where only defined repairs verify and
the window case stays not-tested; synthetic labeling throughout
("previously generated results", "never production recovery").
Conceptual (not in product): multi-user access, customer data
ingestion, notifications, trend analysis across missions.

## Phase 3 — Adversarial challenges vs actual functionality

1. Incorrect stakeholder claim → dispatcher/manager contradiction is
   surfaced as reported assertion, never endorsed (edge `asserts`,
   status `reported`). HOLDS.
2. Conflicting evidence → shown side-by-side with provenance. HOLDS.
3. Missing ack timestamp → incomplete-window classification, never a
   confirmed miss. HOLDS.
4. Partially observed deadline → same guard. HOLDS.
5. Unsupported root-cause assertion → rejected at validation; UI
   states "No confidence score is assigned". HOLDS.
6. Approval confused with execution → Decision Room states "approval
   never executes anything"; report `executed: false`. HOLDS with a
   caveat (persona 2 below).
7. Synthetic repair mistaken for production repair → "Verified means
   only: the specified synthetic repair passed its defined post-repair
   checks — never production recovery." HOLDS, but the word
   "verified" still carries halo risk (personas 4, 5).

## Phase 5 — Decision

**REVISE BEFORE HUMAN TESTING** — no critical defect, but three
moderate revisions (terminology halo around "verified", first-run
orientation burden, decision-trace export gap) should land before the
five guided sessions so findings reflect the product, not its labels.

Untested hypotheses requiring real customers: whether operators value
prediction-locking discipline; whether the evidence taxonomy transfers
to their domains; whether anyone would pay.
