"""First investigation workspace. Stdlib only, in-memory."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field


@dataclass
class Workspace:
    id: str
    name: str
    status: str = "open"


class WorkspaceStore:
    """In-memory workspace registry."""

    def __init__(self) -> None:
        self._items: dict[str, Workspace] = {}
        self._counter = itertools.count(1)

    def create(self, name: str, status: str = "open") -> Workspace:
        wid = f"ws-{next(self._counter):04d}"
        ws = Workspace(id=wid, name=name, status=status)
        self._items[wid] = ws
        return ws

    def get(self, workspace_id: str) -> Workspace | None:
        return self._items.get(workspace_id)

    def list(self) -> list[Workspace]:
        return list(self._items.values())
