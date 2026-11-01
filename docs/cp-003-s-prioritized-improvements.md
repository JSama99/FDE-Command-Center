# CP-003.2-S — Prioritized Improvements (AI-SIMULATED input)

Ranked by severity × evidence strength ÷ effort. "Evidence" below
means simulated-panel agreement plus source-code grounding, NOT human
observation. No item is authorized for implementation by this document.

## Must-fix before human sessions (moderate, low effort)

1. Plain-language outcome line in Decision Room (P2 misread
   "supported" as "solved"). One sentence: what was learned and what
   remains open. Effort: tiny. Effect: removes the top
   misinterpretation risk.
2. Rename display label "verified" → "checks passed (synthetic)" on
   recovery records (P4, P5 halo concern). Backend statuses unchanged.
   Effort: tiny.
3. First-run orientation strip (P5, P2): three-bullet "how to read
   this screen" on Investigation and Chaos Lab. Effort: small.

## Should-fix soon (moderate value, small–medium effort)

4. Discoverable evidence-pack export (P3): surface the existing JSON
   report download as a button. No new capability.
5. Copyable citations (P1): click-to-copy evidence references for
   tickets. Presentation only.
6. Case-event timeline (P1): chronological view of the 7 eligible
   rows. Read-only rendering of existing data.

## Explicitly deferred (out of scope pressure — do not build for P5)

7. SLA/RAG translation, cost framing, multi-case comparison, PDF
   export, API-first workflows. Valuable signals for later
   milestones, but each expands scope and P5-pleasing risks the
   evidentiary discipline that is the product.

## Unverified assumptions needing real customers

- Operators value locked-prediction discipline vs find it bureaucratic.
- The evidence taxonomy transfers outside dispatch-shaped problems.
- Anyone would pay, and who (FDE, manager, consultant?).
