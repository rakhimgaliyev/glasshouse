"""glasshouse — see what your agent is doing before it does it."""

from .events import (
    ApprovalRequested,
    ApprovalResolved,
    DryRunPlanned,
    Event,
    RunFinished,
    RunStarted,
    Thinking,
    ToolFailed,
    ToolFinished,
    ToolProgress,
    ToolSkipped,
    ToolStarted,
    UndoFailed,
    Undone,
)
from .policy import Gate, Policy
from .providers import Completion, FakeProvider, Provider, ToolCall, calls, says
from .runtime import Session, ToolExecutionError
from .tools import Effect, Registry, ToolSpec, tool

__version__ = "0.1.0"

__all__ = [
    "ApprovalRequested",
    "ApprovalResolved",
    "Completion",
    "DryRunPlanned",
    "Effect",
    "Event",
    "FakeProvider",
    "Gate",
    "Policy",
    "Provider",
    "Registry",
    "RunFinished",
    "RunStarted",
    "Session",
    "Thinking",
    "ToolCall",
    "ToolExecutionError",
    "ToolFailed",
    "ToolFinished",
    "ToolProgress",
    "ToolSkipped",
    "ToolSpec",
    "ToolStarted",
    "UndoFailed",
    "Undone",
    "__version__",
    "calls",
    "says",
    "tool",
]
