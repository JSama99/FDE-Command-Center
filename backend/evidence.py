"""Layered evidence model for case-001.

Four layers stay distinct:
- POLICY_CLAIM: formal rule, always backed by a VerifiedQuote from policy.md.
- STAKEHOLDER_REPORT: what someone said, always backed by a VerifiedQuote
  from dispatcher.md or manager.md. Never treated as computed fact.
- COMPUTED_BEHAVIOR: deterministic aggregate from events.csv with the rule
  that produced it. Never a quotation.
- INTERPRETATION: hypothesis or reading that references items from the other
  layers. Never presented as observed fact.

One stakeholder report (the floor-2 printer jam) is explicitly tagged
causal_relevance=False. It is recorded for completeness and excluded from
any causal reading. It never enters CSV calculations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

POLICY_CLAIM = "policy_claim"
STAKEHOLDER_REPORT = "stakeholder_report"
COMPUTED_BEHAVIOR = "computed_behavior"
INTERPRETATION = "interpretation"

IRRELEVANT_SYMPTOM_QUOTE = "The only technical issue I have seen is the floor-2 printer jamming on large jobs."


@dataclass(frozen=True)
class EvidenceItem:
    layer: str
    content: str
    source_ref: str
    start: int | None = None
    end: int | None = None
    rule: str = ""
    basis_refs: tuple[str, ...] = ()
    causal_relevance: bool = True


def policy_claim(quote: str, doc_id: str, start: int, end: int) -> EvidenceItem:
    return EvidenceItem(layer=POLICY_CLAIM, content=quote, source_ref=doc_id, start=start, end=end)


def stakeholder_report(
    quote: str, doc_id: str, start: int, end: int, causal_relevance: bool = True
) -> EvidenceItem:
    return EvidenceItem(
        layer=STAKEHOLDER_REPORT,
        content=quote,
        source_ref=doc_id,
        start=start,
        end=end,
        causal_relevance=causal_relevance,
    )


def computed_behavior(content: str, rule: str) -> EvidenceItem:
    return EvidenceItem(layer=COMPUTED_BEHAVIOR, content=content, source_ref="events.csv", rule=rule)


def interpretation(hypothesis: str, basis_refs: list[str]) -> EvidenceItem:
    return EvidenceItem(
        layer=INTERPRETATION, content=hypothesis, source_ref="ledger", basis_refs=tuple(basis_refs)
    )
