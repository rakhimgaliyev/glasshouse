"""Events emitted while an agent runs.

Everything the runtime does becomes an event. That is the whole point: a
caller can render them, log them, or replay them, and nothing happens that
did not announce itself first.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


def _now() -> float:
    return time.time()


@dataclass
class Event:
    """Base event. `kind` is what SSE clients switch on."""

    kind: str = field(init=False, default="event")
    at: float = field(default_factory=_now, kw_only=True)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind
        return data


@dataclass
class RunStarted(Event):
    kind = "run_started"
    prompt: str
    dry_run: bool


@dataclass
class Thinking(Event):
    """Text the model produced alongside its tool calls."""

    kind = "thinking"
    text: str


@dataclass
class ApprovalRequested(Event):
    """The runtime is holding a mutating call until someone says yes."""

    kind = "approval_requested"
    call_id: str
    tool: str
    display: str
    summary: str
    effect: str
    reversible: bool


@dataclass
class ApprovalResolved(Event):
    kind = "approval_resolved"
    call_id: str
    approved: bool
    reason: str | None = None


@dataclass
class ToolStarted(Event):
    kind = "tool_started"
    call_id: str
    tool: str
    display: str
    summary: str
    effect: str


@dataclass
class ToolProgress(Event):
    """Emitted by long-running tools via the `progress` callback."""

    kind = "tool_progress"
    call_id: str
    message: str


@dataclass
class ToolFinished(Event):
    kind = "tool_finished"
    call_id: str
    tool: str
    result: Any
    elapsed_ms: int


@dataclass
class ToolFailed(Event):
    kind = "tool_failed"
    call_id: str
    tool: str
    error: str


@dataclass
class ToolSkipped(Event):
    """Rejected at an approval gate, or previewed instead of run."""

    kind = "tool_skipped"
    call_id: str
    tool: str
    reason: str


@dataclass
class DryRunPlanned(Event):
    """What a mutating tool *would* have done."""

    kind = "dry_run_planned"
    call_id: str
    tool: str
    display: str
    preview: str


@dataclass
class Undone(Event):
    """A previously applied effect was rolled back."""

    kind = "undone"
    call_id: str
    tool: str
    display: str


@dataclass
class UndoFailed(Event):
    kind = "undo_failed"
    call_id: str
    tool: str
    error: str


@dataclass
class RunFinished(Event):
    kind = "run_finished"
    text: str
    turns: int
    applied: int
    rolled_back: int
