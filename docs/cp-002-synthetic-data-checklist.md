# CP-002 — Synthetic-Data Safety Checklist

For local, operator-assisted, synthetic-data demonstrations only.
No step here authorizes real customer data.

## 1. Fictional identities

Every person, organization, and system is invented: no real names,
companies, addresses, phone numbers, emails, employee IDs, or account
numbers. Stakeholder files (`dispatcher.md`, `manager.md`) contain only
fictional roles. Never "borrow" a real incident and rename it — write
a new one or reuse the shipped fixtures.

## 2. Fabricated records and timestamps

Event rows, timestamps, case IDs, and metrics are authored for the
demo and internally consistent. Timestamps must not match real
operational windows in a way that implies a real event. Keep the
fictional clock (2026-09 case-001 data) unless the scenario demands
otherwise, and note any change in the demo brief.

## 3. No personal or confidential information

Before showing any screen or file: no real customer names, no real
user data, no credentials, no internal URLs, no proprietary code or
text (TalonSight or otherwise). The repository's own fixtures are
already synthetic — verify any added fixture with the same bar.

## 4. Fixture review before demo

- `fixtures/case-001/*` and `fixtures/chaos-lab/*` unchanged
  (hash-check against the acceptance manifest when in doubt).
- New fixtures: small, labeled synthetic, with denominators and rules
  stated; misleading-but-nondecisive signals kept nondecisive.
- Withheld outcomes stay out of served files and prompts.

## 5. Labeling

Say "synthetic demonstration" on entry (the app's fictional notice),
on every screenshot, and before any readout. Corrections: hypotheses
are hypotheses; approvals are not executions; hashes are integrity
checks, not truth.

## 6. Screenshots and recordings

Capture only the demo machine; close unrelated windows/tabs; check
terminal scrollback for keys, paths, or private dirs before sharing;
never show `evaluator-private/`, live stores, or approval rationales
that name real people.

## 7. Provider boundaries

No live model call without separate explicit owner authorization.
Mock mode for UI rehearsal. Never paste customer or non-public text
into a model prompt — the demo prompts carry only shipped synthetic
evidence. Redaction is not authorization: anonymized real data is
still real data until the controls in CP-001 R-01–R-04 exist.
