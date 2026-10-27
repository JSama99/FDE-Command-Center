# FDE Command Center — v0.1 Specification

*Renamed 2026-10-26: formerly FDE Mission Control.*

**Status:** v0.1 build spec · written 2026-10-23 · build window Mon Oct 26 12:00 PM – Wed Nov 4 9:00 PM ET
**Companion docs:** `oral-board-defense-design.md` (board contract), `ip-guardrail-checklist.md` (hard IP rules). This spec assumes both; it does not restate them except where the build depends on the detail.

---

## 1. Product summary and judging-axis map

FDE Command Center is an interactive deployment-engineering simulator. The player, acting as a forward-deployed engineer, has five sim-days to take a fictional customer's AI system to a launch decision: investigate the deployment by interviewing stakeholders and reading operational artifacts, configure and operate the system live in the PanelPlay console, stress it with Chaos Preflight fault injection, submit a launch recommendation, and defend that recommendation before an oral board. A deterministic simulation engine owns every fact, metric, and outcome; Muse Spark powers only dialogue and interrogation; a deterministic rubric renders the verdict. Mission 01 is "The Launch That Almost Failed."

**Product frame (updated 2026-10-24):** the product is **FDE Command Center** — an AI implementation and failure-investigation copilot. The Mission 01 simulator ("The Launch That Almost Failed") is its demo vehicle. Core system added 2026-10-24: the **Failure Investigation Ledger** (Section 11) — the connective tissue between planning an implementation and proving it works. Principle: *Every recommendation has an assumption. Every failure has an investigation. Every claimed fix needs evidence.*

| Axis | Weight | How it is won |
|---|---|---|
| Impact | 30% | The simulator trains the exact judgment real AI deployments fail without: evidence-based go/no-go decisions defended in a room. The debrief teaches, not just scores. |
| Meta AI Tooling | 25% | Muse Spark does two grounded jobs — stakeholder dialogue inside strict knowledge boundaries, and an oral board that interrogates from structured sim state (read state → cite values → probe gaps). The constraint design is the engineering story. |
| Technical Depth | 20% | Seeded deterministic engine + explicit state machine + "AI asks, rubric decides." Any run is replayable: same seed + same config = same verdict, demonstrable live in front of a judge. |
| Demo | 25% | A two-minute arc with a finale: investigate → break it → fix it → defend it → verdict. Section 7 is the exact route. |

## 2. The fictional customer

**Cedarline Insurance**, a regional property insurer (~600 employees), is five days from launching **ClaimPath AI**, an AI claims-triage assistant that classifies first-notice-of-loss submissions, drafts adjuster summaries, and routes or escalates each claim. Go-live is timed for storm season. The stakes: a catastrophe-claim surge is forecast within two weeks of launch; misrouted or stalled claims mean regulator complaints, press, and policyholder harm. The player's mission: determine whether ClaimPath AI launches Monday, and defend the call.

**Reference numbers (engine constants):** steady traffic 120 req/min; one worker sustains 40 req/min; default config runs 4 workers (160 req/min capacity, 75% baseline utilization); launch bar is ≥97% task success and zero dropped requests; p95 latency SLA is 8s.

**Hidden facts** (ground truth; each is an evidence item when surfaced):

1. **The real peak is 320 req/min, not 200.** The launch brief's 200 figure is last storm season's peak. Marketing launches a mobile claim-filing app the same week, roughly doubling intake. *Surfaces:* asking Priya about launch week, or reading footnote 3 of the launch brief.
2. **The sev-1 escalation path is dead.** Escalations page a legacy pager alias that now lands in an unmonitored mailbox; the on-call rotation was disbanded in a reorg. *Surfaces:* asking Marcus who acknowledges a page, or the escalation log artifact (last 3 test pages unacknowledged for 6+ hours).
3. **Attachments over 10 MB crash the parser.** Crashed workers restart over 30s; under storm load ~15% of submissions carry oversized attachments (photos/scans), so the fault compounds. *Surfaces:* incident ticket INC-2214 in the artifact panel, or asking Dana about last month's outage.
4. **Overflow routing violates data residency.** Claims with medical attachments must stay in-region; the console's "overflow to Region B" option breaks that rule. *Surfaces:* asking Ruth about constraints before launch, or the compliance memo artifact.
5. **The green dashboard is measuring the wrong thing.** The vendor status panel shows API uptime (100%). Actual task success is 91% — below the 97% launch bar — because the triage model silently misroutes multi-peril claims. *Surfaces:* switching the metrics artifact from "uptime" to "task success" view.

## 3. Stakeholders (PanelPlay)

All stakeholder dialogue runs through the model layer, constrained per character to the knowledge boundary below. The engine — not the model — decides when a hidden fact has been surfaced (a fact unlocks when the player asks a question tagged to its topic, or opens its artifact).

- **Dana Whitfield — VP Claims Operations (sponsor).** *Knows:* business stakes, storm deadline, the parser outage happened. *Withholds:* the board has already announced the launch date publicly. *Pressure:* launch on time; frames delays as business failures.
- **Marcus Oyelaran — SRE lead.** *Knows:* the escalation alias is dead and the model endpoint has no failover. *Withholds:* both, unless asked directly — he does not want to be the blocker. *Pressure:* none; passive, precise when cornered.
- **Priya Raman — Growth/Marketing lead.** *Knows:* the mobile app launches the same week and doubles intake. *Withholds:* nothing deliberately — she assumes engineering already knows. *Pressure:* do not slip the marketing launch.
- **Ruth Calloway — Compliance officer.** *Knows:* the data-residency constraint and that it is non-negotiable. *Withholds:* nothing, but she only speaks to what she is asked. *Pressure:* no launch with residency violated, full stop.
- **The Board (oral-board phase).** Played by Muse Spark as a skeptical deployment-review panel under the contract in `oral-board-defense-design.md`: grounded in sim state, Socratic, never reveals hidden facts, never scores.

## 4. Mission flow

1. **Brief (guided, ~2 min).** Mission card, launch brief, default config. Player learns the stated peak is 200 req/min.
2. **Investigate.** Free movement between stakeholder chat and the artifact panel (launch brief, metrics, escalation log, incident tickets, compliance memo). Each surfaced hidden fact becomes a citable evidence item in the player's inventory.
3. **Operate.** PanelPlay console configuration (Section 5 lists the controls). Changes are free until a preflight run starts.
4. **Chaos Preflight.** Three fault contracts (below). Each run is a 30-tick simulation (1 tick = 1 sim-minute), watchable live on the metrics charts; the player may reconfigure and re-run any fault any number of times. All runs are logged; the rubric reads the **final run of each fault** plus whether each was attempted.
5. **Decide.** Full launch / limited pilot / hold, a 2–3 sentence rationale, and evidence items cited from the inventory (only items actually surfaced can be cited).
6. **Defend.** Oral board, fixed **4 rounds**. Rubric thresholds are shown before the defense (transparent grading — the demo teaches judgment, it does not trick). If a board round exposes a configuration gap, the player may exercise **one** rework: re-run a single fault with a new config and amend the recommendation once.
7. **Verdict & debrief.** Rubric breakdown, hidden facts revealed with where they were hiding, the board's questions annotated with what they were probing.

**Fault contracts:**

- **F1 — Storm Surge (capacity).** *Trigger:* traffic ramps 120 → 320 req/min over 10 ticks, holds 20 ticks. *Symptoms:* backlog grows at (inflow − capacity); p95 latency breaches 8s; drops begin once backlog exceeds queue capacity. *Correct mitigations:* capacity ≥ 320 (≥8 workers, fixed or autoscaled). *Fail:* any dropped request, or max backlog > 1,000.
- **F2 — Bad Attachment (technical).** *Trigger:* 15% of requests carry >10 MB attachments; each crashes its worker (30s restart), cutting effective capacity ~35% while active. *Symptoms:* worker error spikes, throughput dip, task success sliding toward ~93%. *Correct mitigations:* input-size guard routing oversized files to a human dead-letter queue (success recovers to ~99%). *Fail:* task success < 97%.
- **F3 — Silent Page (operational).** *Trigger:* a sev-1 condition fires at tick 12 and an escalation is sent. *Symptoms:* with the default legacy alias, the ack timer runs unacknowledged, health status degrades, a customer-visible incident is declared at 10 unacked minutes. *Correct mitigations:* escalation channel set to the monitored rotation, ack timeout ≤ 5 min, fallback chain on (ack lands at +2 min). *Fail:* escalation unacknowledged ≥ 10 sim-minutes.

## 5. Simulation state machine

Mission states: `BRIEFING → INVESTIGATING → CONFIGURING ⇄ PREFLIGHT → DECIDING → DEFENDING → (REWORK → PREFLIGHT, once) → SCORING → DEBRIEF`. Events: `OPEN_ARTIFACT`, `ASK` (stakeholder question, topic-tagged), `FACT_SURFACED`, `SET_CONFIG`, `RUN_FAULT(F1|F2|F3)`, `RUN_COMPLETE`, `SUBMIT_DECISION`, `BOARD_ROUND(n)`, `AMEND`, `SCORE`, `REVEAL`.

The sim core is a pure function: `step(state, config, tick) → state`. Queue math per tick: `served = min(backlog + inflow, capacity)`, `backlog += inflow − served`, drops occur when backlog exceeds the 2,000-request queue. Faults are parameter overlays on inflow, crash rate, and the escalation timer. All randomness comes from a per-fault seeded RNG (seeds fixed in code: F1=101, F2=202, F3=303), so any (config, fault) pair replays identically. The model layer has **no write path** into sim state.

**Console controls → sim parameters:** worker count 2–12 (capacity = workers × 40); autoscale on/off with max workers; input-size guard on/off; escalation channel (legacy alias / monitored rotation); ack timeout 1–15 min; fallback chain on/off; overflow routing (Region A only / Region B allowed — selecting B with medical claims in scope sets the residency-violation flag the rubric reads).

## 6. Deterministic rubric (100 points)

- **Evidence coverage — 30.** Each hidden fact surfaced *and cited* in the decision: 6 pts × 5.
- **Fault outcomes — 35.** Each fault attempted at least once: 5 pts × 3 (15). Final run passing its contract: F1 8, F2 6, F3 6 (20).
- **Decision consistency — 20.** The engine computes the *warranted* decision from final state: all contracts pass and no residency violation → FULL; any contract marginal/failing or a fact unresolved → PILOT; any contract failing uncorrected or residency violated → HOLD. Exact match 20, one step off 10, two steps 0.
- **Oral-board defense — 15.** Each board question carries hidden expected-evidence tags (the sim values and evidence items a strong answer references). Answers are scored by deterministic matching against those tags — cited values, cited evidence, internal consistency with the submitted rationale — never by model judgment. Per `oral-board-defense-design.md`, a strong defense can resolve an ambiguous rationale; it cannot move a threshold above. **Ledger note (2026-10-24):** board tags now include ledger entries — hypotheses recorded, fixes attempted, validation results. A decision citing a fix with no validation record in the ledger scores as inconsistent.

**Verdict bands:** ≥70 LAUNCH-READY · 50–69 PILOT-ONLY · <50 HOLD. The debrief states the split plainly: *"The board questioned you; the rubric decided."*

## 7. Two-minute demo route

- **0:00** Mission card: "Cedarline Insurance. Launch in five days. Storm season in twelve." Click **Begin investigation**.
- **0:15** Chat Priya: "Anything else launching that week?" → the mobile app reveal: real peak is 320. Evidence item 1 lands in the inventory.
- **0:40** Console, defaults untouched (4 workers). Click **Run F1 · Storm Surge** → backlog climbs past 1,000, requests drop, chart goes red.
- **0:55** The failure auto-opens a **Ledger draft** (marked synthetic): FAIL-001, observed vs expected, competing hypotheses (capacity shortfall / queue config / traffic model wrong). The player records the capacity hypothesis, applies the fix live (workers 4 → 8, autoscale on), re-runs F1 → backlog drains, zero drops. The Ledger entry records the fix **and the validation run** — the failure is not closed on the fix alone.
- **1:15** Run **F3 · Silent Page** on the default escalation channel → ack timer hits 10:00 unacked, incident declared. Second Ledger entry: hypotheses (routing / transport / ack recording). Suggested next experiment: inspect the destination identity and routing config. Switch channel to monitored rotation, re-run → ack at 2:00, validated.
- **1:30** Decide: **Limited pilot**, citing evidence items 1 and 2 plus both validated ledger entries. Board round: *"Your preflight passed at 320. Why not full launch?"* Player answers citing F2's unmitigated crash rate from their run log and the open ledger entry.
- **1:50** Verdict card: **78/100 · PILOT-ONLY band, recommendation consistent.** "The board questioned you; the rubric decided." Footer: *Built with Muse Spark Open.*

## 8. Build plan, Oct 26 – Nov 4 (solo builder + AI assistance)

Reprioritized 2026-10-24: the Failure Ledger (Section 11) outranks the visual Chaos Preflight feature. One visual preflight scenario ships only if time permits on Day 8; the faults themselves still run as engine runs feeding the Ledger from Day 6 onward.

- **Mon Oct 26 (Day 1):** Fresh repo; sim core (tick engine, queue math, seeded RNG), state machine, and a `ModelClient` interface with a **scripted deterministic implementation** (stakeholder lines and board questions served from data files). No live model, no credits needed — the whole skeleton plays end-to-end by tonight.
- **Tue Oct 27 (Day 2):** Customer requirements + Proof-of-Value Contract screen: what must work (≥97% task success, zero drops, ack ≤ 5 min, no residency violation) and how success is measured (the contracts the rubric reads). PanelPlay console: config controls wired to sim parameters; live metrics charts (backlog, latency, task success); run logging. Live Muse Spark swap can follow once run logging lands (credits landed Oct 26; contract specified in §12).
- **Wed Oct 28 (Day 3):** Muse-powered analysis: topic-tagged questions, fact-surfacing rules, evidence inventory; scripted stakeholder content written against the knowledge boundaries.
- **Thu Oct 29 (Day 4):** AI Decision Challenge: the decision screen ("is this the right implementation approach?"), rationale + evidence citation, decision-consistency computation.
- **Fri Oct 30 (Day 5):** Failure Ledger core: record model (Section 11 fields), event-sourced investigation history, hypothesis tracking, AI-suggested next diagnostic action.
- **Sat Oct 31 (Day 6):** Ledger wiring: Chaos Preflight fault contracts F1–F3 with overlays and pass/fail evaluation; every fault run auto-creates a draft ledger entry marked synthetic; artifact panel (brief, metrics with uptime/task-success toggle, escalation log, INC-2214, compliance memo).
- **Sun Nov 1 (Day 7):** Corrective-action validation + readiness updates: fix logging, retest, validation rule (no resolution without a validation record), readiness report. Guardrail audit script written and run. **Live swap — moved up (credits landed Oct 26):** the live Muse Spark `ModelClient` behind the existing interface can be implemented as soon as Day 2 console/run logging lands; it no longer waits on Nov 1. The scripted implementation stays as fallback, so the swap is reversible and the rubric stays deterministic either way.
- **Mon Nov 2 (Day 8):** Tests + one visual preflight scenario if time permits (F1 Storm Surge as the visual showcase); determinism test (same seed + config → same verdict, three consecutive runs); demo-route hardening: pin seeds, rehearse the Section 7 route to time, UI polish.
- **Tue Nov 3 (Day 9):** Submission package: README, demo video, screenshots, final guardrail audit, submission-form dry run.
- **Wed Nov 4 (Day 10):** Buffer only. Internal deadline **3:00 PM ET**; hard deadline 9:00 PM ET.

## 9. IP guardrails

Per `ip-guardrail-checklist.md`, which governs this build: fresh repo, fresh engine, fresh scenario, built from public chaos-engineering principles (Chaos Monkey, AWS FIS, LitmusChaos) and textbook queue math. **Zero** Chaos Crew code, fixtures, prompts, or designs; **zero** intelligence-core or Scout material; **no** FIELD curriculum content; **no** TalonSight knowledge-base text. What transfers is general FDE craft only. The guardrail audit script (`scripts/audit-guardrail.sh`, banned paths/strings) runs before every commit and before submission. The demo carries the "Built with Muse Spark Open" credit from day one. Pre-submission test for every file: comfortable with Meta holding a perpetual, royalty-free license to it?

## 10. Open decisions / risks

1. **Credits timing — RESOLVED 2026-10-26:** the $150 Meta credits landed Oct 26 (mail arrived 7:26 AM ET, user-confirmed that evening). The live swap no longer waits on Nov 1 and moves up to whenever the build calls for it (earliest: after Day 2 console/run logging). Contract wired into §12 on 2026-10-26. If the live client ever proves flaky, ship the scripted board — determinism still carries Technical Depth.
2. **Official Rules still unpublished** as of Oct 23; re-check at kickoff — any restriction on simulated content or second entries changes scope, not architecture.
3. **Free-text defense scoring** can feel brittle; mitigation already in design — answers pair cited-evidence chips with text, and matching weights the chips.
4. **Scope discipline:** Mission 01 only. No second mission until the submission package is finished, however good Day 8 feels.
5. **Solo-builder risk:** with credits landed Oct 26, no remaining task depends on an external event; the whole build is buildable from Day 1.

## 11. Failure Investigation Ledger — core feature (adopted 2026-10-24)

**Product thesis:** FDE Command Center is an AI implementation and failure-investigation copilot. It helps forward-deployed engineers and AI implementation consultants discover where AI creates business value, select appropriate solutions, define measurable success criteria, investigate failures, validate corrective actions, and determine whether customer deployments are ready to proceed. Principle: *Every recommendation has an assumption. Every failure has an investigation. Every claimed fix needs evidence.*

The Ledger is the connective tissue between everything else in the product:

- **AI Decision Challenge** — is this the right implementation approach?
- **Proof-of-Value Contract** — what must work, and how will success be measured?
- **Failure Investigation Ledger** — what failed, why might it have failed, and what have we tried?
- **PanelPlay** — explore system behavior and dependencies.
- **Chaos Preflight** — run controlled fault scenarios.
- **Validated Outcome** — retest, record remaining risks, update deployment readiness.

**What a record holds.** Failure ID; expected behavior; observed behavior; failure category (technical, operational, human/process, unknown); evidence (logs, test reports, timestamps, screenshots, source records); competing hypotheses (possible causes, never assumed root causes); diagnostic experiments (what was tested, what the results showed); attempted fixes (including unsuccessful attempts); owner and status; validation (evidence the issue was corrected and retested).

**How history works.** Every experiment is a new event appended to the record. Unsuccessful attempts are preserved, never overwritten. The assistant's job is to help the FDE decide what to investigate next — recommending the next diagnostic test and explaining which hypotheses the existing evidence supports or contradicts — not to hand over a plausible explanation of what went wrong. The cause is never declared from plausibility alone.

**Resolution rule (hard).** A problem is not marked resolved because a fix was suggested. Resolution requires a recorded corrective action **plus** a repeat-test validation record. Until both exist, the failure stays open and the readiness report says so.

**Synthetic vs observed (hard).** A failure discovered during Chaos Preflight auto-creates a **draft** ledger entry, clearly marked synthetic. Real test evidence lives in separate entries. Simulated failures must never be presented as observed production incidents.

**Example (fictional demonstration, FAIL-001 — critical escalation not acknowledged).** Alert delivery: confirmed. Owner acknowledgment: not confirmed. Competing hypotheses: incorrect owner routing; notification transport failure; acknowledgment not recorded. Next suggested experiment: inspect the destination identity and routing configuration. Current decision: unresolved — delivery is supported by the fictional evidence, acknowledgment is not established, and the failure remains open until corrective action and validation are recorded.

**MVP scope for the ten-day build.** (1) Create a failure record from a requirement or observed test result. (2) Record evidence and hypotheses, with an AI-suggested next diagnostic action. (3) Log an attempted fix and its test outcome, retaining unsuccessful attempts. (4) Mark resolution only after validation, keeping the full investigation history. **Out of scope:** automatic infrastructure repair, live production fault injection, advanced causal graphs, integrations with every monitoring platform. The MVP runs on fictional evidence, local application state, and a small deterministic investigation model; real customer use would require persistent storage, authentication, and stronger access controls.

**Differentiation, stated honestly.** Established issue trackers already record failures, and incident-management products support investigation timelines. The differentiation is not inventing the failure log — it is connecting the failure, competing hypotheses, evidence, corrective tests, and customer acceptance criteria in one FDE-oriented workflow. That is what gives an FDE a reason to return throughout an engagement (plan Monday, failures Tuesday, mitigation Wednesday, updated readiness report Friday) — which is also the subscription argument, though willingness to pay still needs testing.

## 12. Live ModelClient contract — Muse FDE package (wired 2026-10-26)

**Contract files** (staged alongside this spec): `Muse_FDE_System_Instructions_v1.md` (trusted system/developer instructions, never a user attachment), `Muse_FDE_Response_Schema_v1.json` (strict `oia_investigation` schema, v0.1), `Muse_FDE_Knowledge_Base_v1.md` (model-facing domain reference), `Muse_Package_Readme.md` (setup notes). Model: `muse-spark-1.3` Standard mode. Credentials server-side. The Knowledge Base was received 2026-10-26 evening and vetted clean against §9: no Chaos Crew, FIELD, intelligence-core, Scout, or TalonSight material; no sealed benchmark labels, gold answers, or hidden seeds; no book passages, branded proprietary frameworks, or company data. Note: the KB describes a sibling OIA v0.1 wedge (four-artifact investigation path, six-case internal benchmark vs a plain-model baseline) — it is reference material; this spec governs the submission demo. The evaluator blueprint (`FDE_Private_Evaluation_Blueprint_v1.md`, received 2026-10-26) is held sealed and unopened outside the build dir; it never enters model context or any repo.

**Where the live client plugs in.** Behind the existing `ModelClient` interface (the same interface the scripted implementation serves): stakeholder dialogue (Investigate step), the Ledger's AI-suggested next diagnostic action (§11), and oral-board interrogation (Defend step). The scripted implementation stays as fallback.

**What the model may and may not do.** It proposes; it never decides. Evidence is typed as `policy_requirement` / `witness_report` / `recorded_event` / `computed_metric` / `interpretation` / `hypothesis`; quotes only as literal spans in permitted snapshots (failed verification → downgraded to unverified paraphrase or unknown); numbers only from the application-provided typed calculation tool; at least two competing hypotheses with a discriminating test each; predictions written and server-locked before the result is revealed; no verified-root-cause claim without preset validation conditions. Application code enforces access checks, literal-span verification, typed numeric queries, prediction locks, experiment reveal, and final decision approvals. A schema-conformant answer is not necessarily correct — the app post-validates tool references and claim semantics after every response.

**Schema → spec mapping.** `truth_map.formal` / `.reported` / `.recorded` → policy requirements, witness reports, recorded events (brief, metrics, escalation log, INC-2214, compliance memo); `conflicts` / `unknowns` → the Ledger's open questions; `hypotheses` (supporting / contradicting claim IDs, `discriminating_test`, `prediction_if_true`, status including `validated_under_conditions`) → Ledger competing hypotheses; `next_test` (preregistered prediction draft, `authorization_needed`) → the AI-suggested next diagnostic action; `decision` (`proceed_with_bounded_trial` / `gather_evidence` / `revise_approach` / `pause` / `decline`, `reversal_conditions`, `human_approval_required`) → advisory input to the player's recommendation only.

**Boundary (hard).** The deterministic engine owns every fact, metric, and outcome; the deterministic rubric (§6) renders the verdict (LAUNCH-READY / PILOT-ONLY / HOLD). The model never writes sim state, never scores, and its decision states never map directly onto verdict bands. Synthetic-only: the demo claims no shipped roadmap features (production ingestion, enterprise tenancy, long-term learning, automatic remediation, integrations, billing).
