# MC-009.1 — Final Demonstration Walkthrough and Acceptance Plan

Baseline rehearsed: 660 tests OK, 1 pre-existing socket skip. No
production files changed in this milestone; only this document was
added. Every command below was executed during rehearsal except the
live Safari/browser steps, which require the owner.

Conventions: `$ROOT` is `~/Documents/FDE-Command-Center`. `$DEMO` is a
disposable directory, e.g. `/tmp/mc-demo`. Never point rehearsal
commands at the operational `mission-snapshots/` or
`evaluator-private/` without a backup.

## A. Browser walkthrough (Safari, owner)

Server: `python3 -m backend.server --port 8000` from `$ROOT`, then
open `http://localhost:8000/control.html`.

1. Mission Control loads: five workspaces, synthetic-data notice.
2. Investigation: select evidence items; inspector shows source,
   classification, offsets. Verified observations stay distinct from
   stakeholder reports and hypotheses.
3. Hypothesis Lab: compare H-ACK vs H-QUEUE panels; status remains
   "unverified interpretation"; "No confidence score is assigned".
4. Field Mission (`mission.html`): choose the feed-probe diagnostic,
   lock a prediction (human-authored or AI-reviewed with confirmation).
5. Reveal the synthetic outcome (withheld until lock), then assess:
   deterministic `supported`/`contradicted`, never a root-cause proof.
6. Revision (optional mock mode), proposal PROP-002 v1, human decision
   with rationale; report confirms `executed: false`.
7. Chaos Lab: run one allowlisted simulation explicitly; inspect the
   Evaluation tab (TP=2 FP=0 TN=2 FN=0, safety 2/2, C8 unavailable)
   and Recovery tab (assign + feed verified, window not-tested).
8. Restart: stop the server (Ctrl-C), start again, confirm the same
   `mission_run_id`, locked prediction, revealed outcome, and decision
   (this is also the outstanding MC-007 physical restart test).

## B. Terminal walkthrough (rehearsed, exact outputs)

Setup: `export DEMO=/tmp/mc-demo BRL="$ROOT"` (BRL = repo path).

1. Fresh boot (offline rehearsal of server startup):
   `python3 -c "from backend.persistence import boot_context; print(boot_context('$BRL', '$DEMO/store')[1:])"`
   Expected: `('fresh', 'No saved mission found. Starting a new mission run.')`
2. Drive the mission lifecycle through the real request path
   (diagnostic → predict → reveal → assess; see `tests/test_mc008_3.py`
   `run_demo` for the exact payloads). Each step returns 200.
3. Snapshot check: the store holds `mission-mr-….json` at revision 4
   with `"assessment": {"result": "supported", …}`.
4. Issue the synthetic receipt (existing mechanism, isolated dir):
   `python3 -c "from backend.investigation import build_offline_investigation; from backend.receipt import write_receipt; print(write_receipt(build_offline_investigation('$BRL')['investigation'], None, '$BRL', '$DEMO/receipts')['receipt_id'])"`
   Expected: `RECEIPT: <16-hex-id>`.
5. Create the link:
   `python3 -m backend.link_registry --links-dir $DEMO/links --receipts-dir $DEMO/receipts create --store-dir $DEMO/store --run-id <mr-…> --receipt-id <id> --event post-assessment-link --operator <name>`
   Expected: `linked: <link-id> <mr-…> -> <receipt-id> (post-assessment-link)`
6. Verify: same flags with `verify --link-id <link-id>`.
   Expected: `verified: <link-id> all checks pass` (exit 0).
7. Invalid link: repeat `create` with `--event audit-view-link`.
   Expected: `rejected: event-not-ready timestamp audit not viewed; audit link refused` (exit 1).
8. Revoke: `revoke --link-id <link-id> --operator <name>`.
   Expected: `revoked: <link-id>`; re-verify reports `rejected: <link-id> revoked` (exit 1).
9. Restart: boot again against `$DEMO/store`.
   Expected: `restored | Mission <mr-…> restored at revision 4.`
10. Cleanup: `rm -rf $DEMO`.

## C. Integrity conditions (must all hold during demo)

Hypotheses never presented as root cause; synthetic results never
presented as customer results; approvals never presented as
execution; receipt contents never described as the mission event
(the association is the link record); hashes treated as integrity
checks, never proof of truth; historical receipts stay unlinked;
window recovery stays `not-tested`.

## D. Physical acceptance checklist (owner)

- [ ] Control room loads with no console errors; five workspaces navigate.
- [ ] Evidence inspection, H-ACK/H-QUEUE comparison, prediction lock.
- [ ] Reveal → assessment → proposal → decision → 13-section report.
- [ ] Chaos Lab run, evaluation counts, recovery statuses.
- [ ] MC-007 restart: same run id and lifecycle state after restart.
- [ ] Terminal steps B.1–B.10 on a disposable store; backup
      (`cp -r mission-snapshots /tmp/mc-backup`) before touching any
      operational store; restore from backup if needed.
- [ ] Corruption drills only on disposable stores.

## E. Limitations and blockers

Sandbox cannot open listening sockets, so server startup and Safari
steps are owner-executed and marked pending. No blockers found in the
offline rehearsal. Live provider calls, customer data, receipt-link
activation beyond synthetic demo links, and deployment remain
unauthorized and untested by design.

## F. Decision

GO for final demonstration rehearsal: every step above is
reproducible offline with the rehearsed outputs; only physical
browser confirmation is outstanding.
