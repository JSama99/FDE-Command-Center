# CP-003.1 — Participant Session Guide (5 guided sessions)

Local, operator-assisted, synthetic-data only. The operator controls
the computer at all times; the participant never touches credentials,
files, or terminals. No telemetry or recording without explicit
voluntary consent (see Privacy §7).

## 1. Setup (before the participant arrives)

- Fresh disposable store: `FDE_MISSION_STORE=/tmp/cp003-pN python3 -m backend.server --port 8000`.
- Open `http://localhost:8000/control.html` (Mission Control) and
  `mission.html` (Field Mission) in separate tabs.
- Close unrelated windows; check terminal scrollback for secrets.
- Have this guide, the scorecard, and a blank notes sheet ready.

## 2. Minute 0–5 — Participant context (ask, don't pitch)

1. "Walk me through the last operational failure you investigated. What
   was the first thing you looked at?"
2. "How do you currently gather evidence, and where does it live?"
3. "How do you decide when something is a confirmed root cause versus
   still a hypothesis?"
4. "What happens to your investigation notes and decisions afterward —
   can someone else reconstruct what you did?"

## 3. Minute 5–10 — Scenario briefing (no diagnosis given)

Read verbatim: "This is a fictional training demonstration — a made-up
company, made-up people, made-up data. Urgent referrals are going
unacknowledged even though the dispatch system looks healthy. You have
a written policy, two stakeholder accounts that disagree, and an event
log. Two explanations compete: assignment queue delays (H-QUEUE) or an
acknowledgment workflow gap (H-ACK). Some evidence is incomplete. Your
job is to investigate, not to guess the ending."

## 4. Minute 10–22 — Participant-led tasks (no coaching)

- T1 (Overview/Investigation): "Find what the policy requires and
  where exactly it says that."
- T2 (Investigation): "Show me where the two stakeholders disagree,
  and what is verified versus merely reported."
- T3 (Hypothesis Lab): "Compare the two explanations. What would
  change your mind about each?"
- T4 (Field Mission): "Lock a prediction, reveal the outcome, and
  tell me what the result does and does not prove."
- T5 (Decision Room/Chaos Lab): "What is being proposed, what was
  decided, and what does the Chaos Lab evaluation actually verify?"
- Do not correct wrong conclusions during T1–T5; note them silently.

## 5. Minute 22–27 — Value and adoption (neutral wording)

1. "Which parts of what you just did would be useful in your own work?"
2. "What was confusing or unnecessary?"
3. "Would anything here have changed how your last investigation went?"
4. "What would stop you from using something like this?"
5. "If we invited you to a follow-up pilot, what would you need to
   see first?" (Record the answer verbatim; interest ≠ willingness
   to pay — see scorecard.)

## 6. Minute 27–30 — Debrief

Thank them; ask what should be removed or fixed first; confirm how
their notes will be stored and deleted (Privacy §7).

## 7. Privacy procedure

Synthetic case records only; no customer files; no participant
credentials; no confidential incident details; no external server
access. Collect minimal feedback (role title and notes, no names
unless volunteered). Store notes in the operator's private
`evaluator-private/` tree, never in Git; delete raw notes after
results are summarized (≤30 days). Recording only with explicit
opt-in; refusal changes nothing about the session.
