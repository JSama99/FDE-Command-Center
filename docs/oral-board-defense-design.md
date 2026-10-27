# FDE Mission Lab — Oral-Board Defense: interaction design sketch

**Status:** draft for the v0.1 spec · prepared 2026-10-21 · does not replace the spec draft
**Why this exists:** the pivot vetting (2026-10-21) named Meta Tooling (25% of score) as the weak axis as specced — if Muse Spark only chats with stakeholders, judges may score the tooling as decoration. This sketch gives the AI a second visible job: an oral-board defense where Muse Spark interrogates the player's launch recommendation, while the *score* stays deterministic. AI asks, rubric decides.

## Where it sits in the demo arc

1. Investigate (stakeholder dialogue — the AI's first job)
2. Operate (PanelPlay console — configure the deployment)
3. Break it (Chaos Preflight — inject faults, watch, fix, re-run)
4. **Defend it (oral board — the AI's second job)**
5. Verdict (deterministic rubric decides; AI delivers the debrief)

Act 4 is the demo's final act: two minutes, high tension, and the moment judges see Meta's tooling doing work that only reasoning can do — while the fairness-critical scoring stays provably deterministic.

## The mechanic

The player submits:
- a launch recommendation: **full launch / limited pilot / hold**
- a short written rationale (2–3 sentences)
- the evidence items they cite (chosen from the artifacts and sim observations they actually opened)

Muse Spark then runs **3–5 rounds of follow-up questions**, each grounded in the structured sim state — never free-floating.

## The AI's contract (system-prompt boundary)

**It sees:**
- the final sim state (configuration, all preflight runs, before/after metrics)
- the player's recommendation, rationale, and cited evidence
- the hidden-facts list (ground truth the player was supposed to uncover)
- the stakeholder knowledge boundaries (who knew what — so questions respect what the player could have learned)

**It must:**
- ground every question in a specific value from the sim state or a cited artifact ("Your preflight showed backlog accumulating at 120 req/min during the escalation fault, yet your recommendation cites capacity headroom. Walk me through that.")
- probe Socratically — it may steer toward a hidden fact, but never *reveal* it outright; the player has to produce the insight
- adapt: if the player patches a gap in their answer, the next question moves to the next weakest point

**It must never:**
- invent system metrics or scenario facts (it reads the same structured state that drives the console — no secret changes)
- reveal hidden facts directly, hand the player the "right" recommendation, or announce the score
- break character: it is a skeptical deployment-review board, not a helper

## What stays deterministic (the fairness line)

The rubric scores — the AI never does:
- **Evidence coverage:** did the player cite the hidden facts their investigation should have surfaced?
- **Fault coverage:** did preflight runs cover all three fault contracts (technical, capacity, operational/human)?
- **Consistency:** does the recommendation match the rubric thresholds given the observed sim outcomes?

The AI's interrogation feeds the rubric: a strong oral-board defense can resolve an *ambiguous* rationale (cited evidence vs. reasoning quality), but it cannot move a deterministic threshold. The debrief states this plainly: *"The board questioned you; the rubric decided."*

## Why this lands with judges

- **Meta Tooling (25%)** stops being decorative: Muse Spark is doing grounded, state-aware reasoning with tool-use-shaped discipline (read state → cite values → probe gaps). The constraint design (AI reads, never invents) is itself the engineering story.
- **Demo (25%):** the two-minute route now has a finale — run preflight → break it → fix it → *defend it to the board* → verdict. The judge feels the last act.
- **Technical Depth (20%):** "AI asks, rubric decides" is a defensible separation of concerns — nondeterministic reasoning for interrogation, deterministic replay for scoring. That split is replayable live, which provable depth.
- **Impact (30%):** it mirrors the real FDE world: launch decisions are defended in rooms, not clicked in dashboards. That line is straight from Jermaine's firsthand experience.

## Open questions for the spec (not answered here)

- How many rounds before the board renders a verdict — fixed 4, or adaptive (stop when all three rubric dimensions have a clean read)?
- Does the player see the rubric thresholds before the defense (transparent grading) or after (honest under-pressure assessment)? Recommendation: show them — the demo is about learning deployment judgment, not tricking players.
- Do weak answers trigger a second preflight run (re-test and re-defend)? This is the strongest loop for the two-minute demo if time allows: *defend → board finds the gap → re-run preflight → re-defend.* Flag for the spec's demo route.
