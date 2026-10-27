# FDE Command Center

An AI implementation and failure-investigation copilot, built as an interactive
deployment-engineering simulator for the Meta $1M AI Hackathon (Indie track;
event October 26 – November 4, 2026; submissions due November 4, 9:00 PM ET).

> **Principle:** Every recommendation has an assumption. Every failure has an
> investigation. Every claimed fix needs evidence.

## The demo: Mission 01 — "The Launch That Almost Failed"

Cedarline Insurance is launching ClaimPath AI, a claims-triage system. The
player, acting as a forward-deployed engineer, has five sim-days to take it to
a launch decision:

1. **Investigate** — interview stakeholders and read operational artifacts to
   surface the hidden facts.
2. **Operate** — configure the system live in the PanelPlay console.
3. **Break it** — run Chaos Preflight fault injection (Storm Surge, Bad
   Attachment, Silent Page).
4. **Decide** — recommend full launch, limited pilot, or hold, with cited
   evidence.
5. **Defend** — argue the recommendation before an oral board.

A deterministic simulation engine owns every fact, metric, and outcome.
Muse Spark powers only dialogue and interrogation. A deterministic rubric
renders the verdict. At the center sits the **Failure Investigation Ledger**:
competing hypotheses, diagnostic experiments, attempted fixes, and resolution
only after a fix plus a repeat-test validation record.

## Status

Day 1 (October 26, 2026): v0.1 specification and live model contract are in
place; the code build is in progress. Everything in the demo is synthetic and
fictional — no real customer data, and no claim that roadmap features have
shipped.

## Contents

- `docs/fde-command-center-v0.1-spec.md` — the full v0.1 specification (customer,
  stakeholders, fault contracts, rubric, build plan, Failure Ledger).
- `docs/ip-guardrail-checklist.md` — the IP guardrail governing this repo:
  all-fresh build; no intelligence-core, Scout, or Chaos Crew implementation;
  no FIELD curriculum content; no TalonSight knowledge-base text. (The future
  guardrail audit script scans code, prompts, and fixtures — not the guardrail
  docs themselves, which name the banned categories.)
- `docs/oral-board-defense-design.md` — oral-board defense design.
- `muse-fde/` — the live ModelClient contract: system instructions, strict
  `oia_investigation` response schema, domain knowledge base, and setup
  readme. The private evaluation blueprint is deliberately **not** in this
  repo — it is held sealed separately and never enters model context.

## Built with Muse Spark Open

The live model client targets `muse-spark-1.3` (Standard mode) behind the
`ModelClient` interface; a scripted deterministic implementation stays as
fallback, so the rubric stays deterministic either way.

## License

To be decided. As a hackathon submission, the work is subject to the
competition's license terms.
