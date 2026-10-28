"""Strict reporting categories for case-001.

Builds on backend.events without changing its contract. Every number here is
derived from fixtures/case-001/events.csv plus two explicit deadline rules:

- ASSIGN_RULE: assigned_at <= created_at + 1h (from policy.md).
- ACK_RULE: ack present, ack >= created, ack >= assigned when assigned,
  ack <= created_at + 4h (from policy.md and backend.events).

Category discipline (never claim a confirmed failure on weak evidence):
- confirmed_miss: eligible, complete observation window, no valid timely ack,
  no ordering anomaly. Only these are confirmed deadline misses.
- anomalous: eligible with an ordering anomaly. Needs a source check, never a
  confirmed miss.
- incomplete: eligible without a valid timely ack whose window closes before
  the 4h deadline. Insufficient evidence, never a confirmed miss.
- Partition: eligible = within + confirmed + anomalous_complete_or_other +
  incomplete, pairwise disjoint. (In the current fixture the single anomaly has
  a complete window, so eligible = 1 within + 3 confirmed + 1 anomalous + 2
  incomplete = 7.)
"""

from __future__ import annotations

from datetime import timedelta

from .events import CaseEvent, compute_summary, ordering_anomaly

ASSIGN_DEADLINE_HOURS = 1
ACK_DEADLINE_HOURS = 4


def categorize(events: list[CaseEvent]) -> dict[str, list[str]]:
    eligible = [e for e in events if e.triage.strip().upper() == "URGENT"]
    with_assignment = [e for e in eligible if e.assigned_at is not None]
    within_1h = [
        e
        for e in with_assignment
        if e.assigned_at is not None
        and e.assigned_at >= e.created_at
        and e.assigned_at <= e.created_at + timedelta(hours=ASSIGN_DEADLINE_HOURS)
    ]
    summary = compute_summary(events, deadline_hours=ACK_DEADLINE_HOURS)
    within_set = set(summary.within_ids)
    incomplete_set = set(summary.incomplete_ids)
    anomalous_set = set(summary.ordering_anomalies)

    confirmed = [
        e.case_id
        for e in eligible
        if e.case_id not in within_set
        and e.case_id not in incomplete_set
        and e.case_id not in anomalous_set
    ]
    return {
        "eligible": [e.case_id for e in eligible],
        "with_assignment": [e.case_id for e in with_assignment],
        "assigned_within_1h": [e.case_id for e in within_1h],
        "assigned_late": [e.case_id for e in with_assignment if e.case_id not in {x.case_id for x in within_1h}],
        "valid_ack_within_4h": list(summary.within_ids),
        "confirmed_miss": confirmed,
        "anomalous": list(summary.ordering_anomalies),
        "incomplete": list(summary.incomplete_ids),
    }
