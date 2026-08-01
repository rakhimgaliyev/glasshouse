"""When to stop and ask a human."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .tools import Effect, ToolSpec


class Gate(str, Enum):
    NEVER = "never"
    """Trust the agent. Nothing is gated."""

    ON_DESTRUCTIVE = "on_destructive"
    """Ask only before something that cannot be taken back."""

    ON_MUTATION = "on_mutation"
    """Ask before anything that changes state. The sane default."""

    ALWAYS = "always"
    """Ask before every call, reads included. Useful while debugging."""


@dataclass(frozen=True)
class Policy:
    gate: Gate = Gate.ON_MUTATION

    require_undo_for_destructive: bool = False
    """Refuse to run a destructive tool that has no undo handler."""

    def needs_approval(self, spec: ToolSpec) -> bool:
        if self.gate is Gate.ALWAYS:
            return True
        if self.gate is Gate.NEVER:
            return False
        if self.gate is Gate.ON_MUTATION:
            return spec.effect.mutating
        return spec.effect is Effect.DESTRUCTIVE
