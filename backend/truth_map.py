"""Operational Truth Map: policy, stakeholder statements, recorded events.

The three evidence types stay distinct. No merging, no inference here.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field


@dataclass
class PolicyExcerpt:
    id: str
    workspace_id: str
    text: str
    source: str = "fictional-policy-manual"


@dataclass
class StakeholderStatement:
    id: str
    workspace_id: str
    speaker_role: str
    text: str


@dataclass
class RecordedEvent:
    id: str
    workspace_id: str
    kind: str
    detail: str


@dataclass
class OperationalTruthMap:
    workspace_id: str
    policies: list[PolicyExcerpt] = field(default_factory=list)
    statements: list[StakeholderStatement] = field(default_factory=list)
    events: list[RecordedEvent] = field(default_factory=list)


class TruthMapStore:
    def __init__(self) -> None:
        self._maps: dict[str, OperationalTruthMap] = {}
        self._counter = itertools.count(1)

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._counter):04d}"

    def for_workspace(self, workspace_id: str) -> OperationalTruthMap:
        m = self._maps.get(workspace_id)
        if m is None:
            m = OperationalTruthMap(workspace_id=workspace_id)
            self._maps[workspace_id] = m
        return m

    def add_policy(self, workspace_id: str, text: str, source: str = "fictional-policy-manual") -> PolicyExcerpt:
        item = PolicyExcerpt(id=self._next_id("pol"), workspace_id=workspace_id, text=text, source=source)
        self.for_workspace(workspace_id).policies.append(item)
        return item

    def add_statement(self, workspace_id: str, speaker_role: str, text: str) -> StakeholderStatement:
        item = StakeholderStatement(
            id=self._next_id("stmt"), workspace_id=workspace_id, speaker_role=speaker_role, text=text
        )
        self.for_workspace(workspace_id).statements.append(item)
        return item

    def add_event(self, workspace_id: str, kind: str, detail: str) -> RecordedEvent:
        item = RecordedEvent(id=self._next_id("evt"), workspace_id=workspace_id, kind=kind, detail=detail)
        self.for_workspace(workspace_id).events.append(item)
        return item
