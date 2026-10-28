"""Muse Spark 1.3 integration seam (Meta Model API).

No network, no SDK, no credentials here. The domain depends only on
ModelClient. A real Meta Model API client can implement the same protocol
later without touching workspace/truth-map/ledger code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ModelConfig:
    model_name: str = "muse-spark-1.3"
    endpoint: str = ""
    configured: bool = False


class ModelClient(Protocol):
    def summarize(self, prompt: str) -> str:
        ...


class NoOpModelClient:
    """Placeholder used until a Meta Model API client is wired in."""

    def __init__(self, config: ModelConfig | None = None) -> None:
        self.config = config or ModelConfig()

    def summarize(self, prompt: str) -> str:
        return "fictional-summary: model not configured"
