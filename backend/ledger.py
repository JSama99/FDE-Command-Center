"""Basic Failure Investigation Ledger. Insertion-ordered, per workspace."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field


@dataclass
class LedgerEntry:
    id: str
    workspace_id: str
    hypothesis: str
    evidence_refs: list[str] = field(default_factory=list)
    status: str = "open"


class LedgerStore:
    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []
        self._counter = itertools.count(1)

    def append(
        self,
        workspace_id: str,
        hypothesis: str,
        evidence_refs: list[str] | None = None,
        status: str = "open",
    ) -> LedgerEntry:
        entry = LedgerEntry(
            id=f"led-{next(self._counter):04d}",
            workspace_id=workspace_id,
            hypothesis=hypothesis,
            evidence_refs=list(evidence_refs or []),
            status=status,
        )
        self._entries.append(entry)
        return entry

    def list_for(self, workspace_id: str) -> list[LedgerEntry]:
        return [e for e in self._entries if e.workspace_id == workspace_id]

    def list_all(self) -> list[LedgerEntry]:
        return list(self._entries)
