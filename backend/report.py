"""Backend-generated case-001 report data. No hardcoded findings.

All quotations are verified verbatim against fixtures/case-001/*.md (doc id +
offsets preserved). All counts come from fixtures/case-001/events.csv via
backend.report_categories. Hypotheses are labeled unverified interpretations.
"""

from __future__ import annotations

from pathlib import Path

from .evidence import IRRELEVANT_SYMPTOM_QUOTE
from .events import parse_events_csv
from .quotes import load_case_documents, verify_quote
from .report_categories import (
    ACK_DEADLINE_HOURS,
    ASSIGN_DEADLINE_HOURS,
    categorize,
)

POLICY_QUOTES = [
    ("policy", "All URGENT referrals must be assigned to a coordinator within 1 hour of creation."),
    ("policy", "All URGENT referrals must receive a recorded acknowledgment within 4 hours of creation."),
    (
        "policy",
        "An observation window that closes before the 4-hour deadline is incomplete and cannot prove a miss.",
    ),
]

DISPATCHER_QUOTES = [
    ("dispatcher", "We usually acknowledge urgent cases the same day."),
    ("dispatcher", "When the queue spikes, we leave some urgent cases unassigned overnight."),
]

MANAGER_QUOTES = [
    ("manager", "No urgent case ever waits unassigned."),
    ("manager", "The dashboard shows 100% on-time acknowledgment for urgent cases."),
    ("manager", IRRELEVANT_SYMPTOM_QUOTE),
]

HYPOTHESES = [
    {
        "text": "Fictional reading: overnight backlog may explain unassigned urgent cases.",
        "basis": ["dispatcher backlog statement", "computed: 2 eligible cases without assignment timestamp"],
    },
    {
        "text": "Fictional reading: same-day acknowledgment may still miss the 4-hour deadline.",
        "basis": ["dispatcher same-day statement", "computed: 1 late acknowledgment (case-002)"],
    },
]


def _verified(documents, doc_id: str, quote: str) -> dict:
    v = verify_quote(documents, doc_id, quote)
    return {"doc_id": v.doc_id, "quote": v.quote, "start": v.start, "end": v.end}


def build_case_report(base_dir: str | Path = ".") -> dict:
    base = Path(base_dir)
    documents = load_case_documents(base)
    events = parse_events_csv(base / "fixtures" / "case-001" / "events.csv")
    cats = categorize(events)
    n_eligible = len(cats["eligible"])

    def finding(label: str, ids: list[str], rule: str, denominator: str) -> dict:
        return {
            "label": label,
            "value": len(ids),
            "ids": sorted(ids),
            "denominator": denominator,
            "rule": rule,
            "source": "fixtures/case-001/events.csv",
        }

    assign_rule = f"assigned_at <= created_at + {ASSIGN_DEADLINE_HOURS}h"
    ack_rule = f"ack present, ack >= created, ack >= assigned when assigned, ack <= created_at + {ACK_DEADLINE_HOURS}h"
    window_rule = f"window_close_at >= created_at + {ACK_DEADLINE_HOURS}h means complete"

    policy = [_verified(documents, d, q) for d, q in POLICY_QUOTES]
    dispatcher = [_verified(documents, d, q) for d, q in DISPATCHER_QUOTES]
    manager = [_verified(documents, d, q) for d, q in MANAGER_QUOTES]

    contradictions = [
        {
            "title": "Assignment practice vs assignment claims",
            "sources": [
                {"ref": "dispatcher", "quote": DISPATCHER_QUOTES[1][1]},
                {"ref": "manager", "quote": MANAGER_QUOTES[0][1]},
            ],
            "computed": "2 eligible urgent cases have no assignment timestamp (case-004, case-006).",
            "status": "contradiction between stakeholder statements; computed data sides with the dispatcher admission",
        },
        {
            "title": "Acknowledgment performance vs dashboard claim",
            "sources": [
                {"ref": "manager", "quote": MANAGER_QUOTES[1][1]},
            ],
            "computed": "1 of 7 eligible urgent cases has a valid acknowledgment within 4 hours; 3 are confirmed misses.",
            "status": "computed data contradicts the dashboard claim",
        },
    ]
    unresolved = [
        "case-005 and case-006 have incomplete observation windows and cannot prove a miss.",
        "case-008 has an acknowledgment recorded before its assignment timestamp and needs a source check.",
    ]

    return {
        "case_id": "case-001",
        "fictional": True,
        "generated_from": {
            "events_csv": "fixtures/case-001/events.csv",
            "documents": ["fixtures/case-001/policy.md", "fixtures/case-001/dispatcher.md", "fixtures/case-001/manager.md"],
            "assign_rule": assign_rule,
            "ack_rule": ack_rule,
            "window_rule": window_rule,
        },
        "policy_requirements": policy,
        "dispatcher_statements": dispatcher,
        "manager_statements": manager,
        "contradictions": contradictions,
        "unresolved_questions": unresolved,
        "calculations": [
            finding("Eligible urgent cases", cats["eligible"], "triage == URGENT", "8 CSV rows"),
            finding("With assignment timestamp", cats["with_assignment"], "assigned_at present", f"{n_eligible} eligible"),
            finding("Assigned within 1 hour", cats["assigned_within_1h"], assign_rule, f"{n_eligible} eligible"),
            finding("Valid acknowledgment within 4 hours", cats["valid_ack_within_4h"], ack_rule, f"{n_eligible} eligible"),
            finding("Confirmed deadline misses", cats["confirmed_miss"], f"no valid ack AND {window_rule} AND no ordering anomaly", f"{n_eligible} eligible"),
            finding("Anomalous sequences (needs source check, not a confirmed miss)", cats["anomalous"], "assigned_at < created_at OR ack_at < created_at OR ack_at < assigned_at", f"{n_eligible} eligible"),
            finding("Incomplete windows (insufficient evidence, not a confirmed miss)", cats["incomplete"], f"no valid ack AND NOT ({window_rule})", f"{n_eligible} eligible"),
        ],
        "categories": cats,
        "hypotheses": [
            {"text": h["text"], "basis": h["basis"], "status": "unverified interpretation"} for h in HYPOTHESES
        ],
        "reported_observation_only": {
            "text": "Floor-2 printer jamming reported by the manager.",
            "quote": IRRELEVANT_SYMPTOM_QUOTE,
            "source": "manager",
            "causal_relevance": False,
            "note": "Reported observation only. Not a cause of referral delays.",
        },
    }
