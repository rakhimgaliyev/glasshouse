"""The provider seam.

The runtime never imports a vendor SDK. It asks a Provider for the next
step and gets back a normalised Completion. That is what lets the whole
library be exercised in tests without a network call or an API key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class Completion:
    """One model turn, normalised."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


@runtime_checkable
class Provider(Protocol):
    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Completion:
        """Take the conversation so far, return the next turn."""
        ...
