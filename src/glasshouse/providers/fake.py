"""A scripted provider.

Every test and the demo run on this. No API key, no network, no cost, and
the agent's behaviour is exactly reproducible — which is the only way to
write assertions about an agent loop that mean anything.
"""

from __future__ import annotations

from typing import Any

from .base import Completion, Provider, ToolCall


class FakeProvider(Provider):
    def __init__(self, script: list[Completion]) -> None:
        if not script:
            raise ValueError("script must not be empty")
        self._script = list(script)
        self.calls: list[list[dict[str, Any]]] = []

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Completion:
        self.calls.append(messages)
        if not self._script:
            return Completion(text="(script exhausted)")
        return self._script.pop(0)

    @property
    def turns_used(self) -> int:
        return len(self.calls)


def says(text: str) -> Completion:
    """Shorthand: the model answers and stops."""
    return Completion(text=text)


def calls(*specs: tuple[str, dict[str, Any]], text: str = "") -> Completion:
    """Shorthand: the model asks for one or more tools.

    >>> calls(("read_file", {"path": "a.txt"}))
    """
    return Completion(
        text=text,
        tool_calls=[
            ToolCall(id=f"call_{i}", name=name, args=args)
            for i, (name, args) in enumerate(specs)
        ],
    )
