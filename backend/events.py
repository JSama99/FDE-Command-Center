"""Deterministic CSV event calculations for case-001.

All numbers are computed from fixtures/case-001/events.csv. Nothing is
generated or estimated. Stdlib only (csv + datetime).

Rules (fictional simplification, wall-clock hours):
- Eligible: triage.strip().upper() == "URGENT".
- Assigned: assigned_at present.
- Deadline: created_at + deadline_hours (default 4).
- Complete window: window_close_at >= deadline. Incomplete otherwise.
- Valid timely ack: ack present, ack >= created, ack >= assigned (when
  assigned), ack <= deadline.
- ack_within_deadline: eligible with a valid timely ack.
- incomplete_windows: eligible without a valid timely ack whose window closes
  before the deadline. These cannot prove a miss and are excluded from the
  lacking count.
- lacking_ack_within_deadline: eligible minus within minus incomplete.
- Ordering anomalies: assigned_at < created_at, ack_at < created_at, or
  (assigned and ack present with ack_at < assigned_at). Flagged by case id;
  anomalous acks never count as within deadline.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class CaseEvent:
    case_id: str
    triage: str
    created_at: datetime
    assigned_at: datetime | None
    ack_at: datetime | None
    window_close_at: datetime


@dataclass(frozen=True)
class ComputationSummary:
    total_eligible_urgent: int
    assigned_urgent: int
    ack_within_deadline: int
    lacking_ack_within_deadline: int
    incomplete_windows: int
    ordering_anomalies: tuple[str, ...]
    within_ids: tuple[str, ...]
    lacking_ids: tuple[str, ...]
    incomplete_ids: tuple[str, ...]


def _parse_opt(value: str) -> datetime | None:
    value = value.strip()
    return datetime.fromisoformat(value) if value else None


def parse_events_csv(path: str | Path) -> list[CaseEvent]:
    rows: list[CaseEvent] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            created = datetime.fromisoformat(row["created_at"].strip())
            rows.append(
                CaseEvent(
                    case_id=row["case_id"].strip(),
                    triage=row["triage"].strip(),
                    created_at=created,
                    assigned_at=_parse_opt(row.get("assigned_at", "")),
                    ack_at=_parse_opt(row.get("ack_at", "")),
                    window_close_at=datetime.fromisoformat(row["window_close_at"].strip()),
                )
            )
    rows.sort(key=lambda e: (e.created_at, e.case_id))
    return rows


def ordering_anomaly(event: CaseEvent) -> bool:
    if event.assigned_at is not None and event.assigned_at < event.created_at:
        return True
    if event.ack_at is not None and event.ack_at < event.created_at:
        return True
    if event.assigned_at is not None and event.ack_at is not None and event.ack_at < event.assigned_at:
        return True
    return False


def compute_summary(events: list[CaseEvent], deadline_hours: int = 4) -> ComputationSummary:
    deadline = timedelta(hours=deadline_hours)
    eligible = [e for e in events if e.triage.strip().upper() == "URGENT"]

    anomalies = tuple(e.case_id for e in eligible if ordering_anomaly(e))
    anomalous = set(anomalies)

    within: list[str] = []
    incomplete: list[str] = []
    for e in eligible:
        cutoff = e.created_at + deadline
        valid_ack = (
            e.case_id not in anomalous
            and e.ack_at is not None
            and e.ack_at <= cutoff
        )
        if valid_ack:
            within.append(e.case_id)
        elif e.window_close_at < cutoff:
            incomplete.append(e.case_id)

    within_set = set(within)
    incomplete_set = set(incomplete)
    lacking = tuple(e.case_id for e in eligible if e.case_id not in within_set and e.case_id not in incomplete_set)
    assigned = sum(1 for e in eligible if e.assigned_at is not None)

    return ComputationSummary(
        total_eligible_urgent=len(eligible),
        assigned_urgent=assigned,
        ack_within_deadline=len(within),
        lacking_ack_within_deadline=len(lacking),
        incomplete_windows=len(incomplete),
        ordering_anomalies=anomalies,
        within_ids=tuple(within),
        lacking_ids=lacking,
        incomplete_ids=tuple(incomplete),
    )
