# FDE Mission Lab — IP Guardrail Checklist (hard rules for the Oct 26–Nov 4 build window)

**Status:** standing checklist, prepared 2026-10-21 · pin this during the build
**Why it exists:** Jermaine's standing reminder is "keep IP in mind." The extended guardrail for the pivot: intelligence-core, Scout, and Chaos Crew implementation never enter any submission repo — Meta/Cerebral Valley receive a perpetual, irrevocable, worldwide, royalty-free license to whatever is submitted. This checklist makes that concrete for Mission Lab.

## The one rule

**Mission Lab builds fresh:** fresh repo, fresh engine, fresh scenarios — from public chaos-engineering principles only, written for this project.

## NEVER goes in the submission repo

- Any code, prompts, fixtures, or models from **intelligence-core** (the standalone TalonSight Intelligence codebase)
- Any **Chaos Crew** source, simulation models, prompts, test fixtures, or designs — the memo's own condition, made absolute
- Any **Scout** code, prompts, or fixtures
- Any **FIELD curriculum** content (methodology specifics, lesson text, exercises)
- Any **TalonSight knowledge-base text** — the Receipts repo carries a path-scoped KB-text audit exclusion; Mission Lab keeps KB text out entirely
- TalonSight-specific methodology beyond general FDE craft (see below)

## ALLOWED — build from these only

- Public chaos-engineering principles: Netflix Chaos Monkey, AWS Fault Injection Service, LitmusChaos — prior art for anyone, implemented independently
- Public-domain queue-capacity math (the simplified traffic/worker/backlog model is textbook, not proprietary)
- General FDE craft: deployment-review habits, stakeholder interview patterns, launch-readiness criteria, the investigator→operator→decision loop
- His own new scenario writing: fictional customers, hidden facts, stakeholder roles, fault contracts — all written fresh for the mission
- Muse Spark Open / open-weights models for the AI layer, with the "Built with Muse Spark Open" credit line in the demo footer from day one

## The audit

- Carry over the guardrail audit pattern from the Receipts repo (`scripts/audit-guardrail.sh`): a script that scans the new repo for banned paths and strings (intelligence-core dir names, chaos-crew/scout module names, FIELD curriculum markers, KB text fingerprints) and fails the build on any hit.
- Run it before every commit during the build window and before submission. An audit that fails in CI is a guardrail; an audit run by memory is a wish.

## The bright lines

- **"Inspired by my FDE experience"** → fine. The FIELD loop is a real operating model; general craft transfers.
- **"Ported from my existing implementation"** → not fine. Rewriting Chaos Crew logic from memory is still Chaos Crew in the repo — write the engine from public principles and the new scenario's needs.
- **"The spec references my methodology"** → the v0.1 spec should describe the *mission's* logic (hidden facts, fault contracts, rubric), not the *methodology's* logic. If a spec section only makes sense inside TalonSight's internal doctrine, cut it.

## Remember at submission time

The perpetual license grant covers the submission repo — code, docs, demo assets. Review the repo once before submitting with one question: *"Am I comfortable with Meta holding a permanent, royalty-free license to every line in here?"* If the answer is yes for every file, the guardrail held.
