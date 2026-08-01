"""The agent loop, with the lid off.

A normal agent loop is a black box: the model asks for tools, they run, you
get an answer. This one yields an event for every decision, refuses to apply
a mutating call until someone approves it, can run the whole thing without
touching anything (dry run), and unwinds what it already did when a later
step blows up.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

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
from .policy import Policy
from .providers.base import Provider, ToolCall
from .tools import Registry, ToolSpec


class ToolExecutionError(RuntimeError):
    """A tool raised. Carries the call id so the journal can be unwound."""

    def __init__(self, call_id: str, tool: str, cause: BaseException) -> None:
        super().__init__(f"{tool} failed: {cause}")
        self.call_id = call_id
        self.tool = tool
        self.cause = cause


@dataclass
class AppliedEffect:
    """One mutating call that actually happened, kept so it can be undone."""

    call_id: str
    spec: ToolSpec
    args: dict[str, Any]


@dataclass
class Decision:
    approved: bool
    reason: str | None = None


class Session:
    """One agent run.

    Drive it by iterating. When an :class:`ApprovalRequested` comes out, call
    :meth:`approve` or :meth:`reject` before asking for the next event — the
    runtime is holding that call and will not proceed until you decide.

        session = Session(provider, registry)
        for event in session.run("clean up the temp files"):
            if isinstance(event, ApprovalRequested):
                session.approve(event.call_id)
    """

    def __init__(
        self,
        provider: Provider,
        registry: Registry,
        *,
        policy: Policy | None = None,
        dry_run: bool = False,
        max_turns: int = 12,
        auto_undo: bool = True,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.policy = policy or Policy()
        self.dry_run = dry_run
        self.max_turns = max_turns
        self.auto_undo = auto_undo

        self._decisions: dict[str, Decision] = {}
        self._journal: list[AppliedEffect] = []
        self._rolled_back = 0

    # ------------------------------------------------------------------ #
    # approval channel
    # ------------------------------------------------------------------ #

    def approve(self, call_id: str, reason: str | None = None) -> None:
        self._decisions[call_id] = Decision(True, reason)

    def reject(self, call_id: str, reason: str | None = None) -> None:
        self._decisions[call_id] = Decision(False, reason)

    # ------------------------------------------------------------------ #
    # the loop
    # ------------------------------------------------------------------ #

    def run(self, prompt: str) -> Iterator[Event]:
        yield RunStarted(prompt=prompt, dry_run=self.dry_run)

        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        payload = self.registry.as_payload()
        applied = 0
        final_text = ""
        turns = 0

        for turn in range(self.max_turns):
            turns = turn + 1
            completion = self.provider.complete(messages, payload)

            if completion.text:
                final_text = completion.text
                yield Thinking(text=completion.text)

            if not completion.wants_tools:
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": completion.text,
                    "tool_calls": [
                        {"id": c.id, "name": c.name, "args": c.args}
                        for c in completion.tool_calls
                    ],
                }
            )

            results: list[dict[str, Any]] = []
            for call in completion.tool_calls:
                try:
                    events, result, did_apply = yield from self._handle(call)
                except ToolExecutionError as exc:
                    yield ToolFailed(call_id=exc.call_id, tool=exc.tool, error=str(exc.cause))
                    if self.auto_undo:
                        yield from self._unwind()
                    yield RunFinished(
                        text=final_text,
                        turns=turns,
                        applied=applied,
                        rolled_back=self._rolled_back,
                    )
                    return
                del events  # already yielded
                applied += int(did_apply)
                results.append({"tool_call_id": call.id, "content": result})

            # All results go back in one message — splitting them teaches the
            # model to stop making parallel calls.
            messages.append({"role": "user", "tool_results": results})

        yield RunFinished(
            text=final_text,
            turns=turns,
            applied=applied,
            rolled_back=self._rolled_back,
        )

    # ------------------------------------------------------------------ #
    # one tool call
    # ------------------------------------------------------------------ #

    def _handle(self, call: ToolCall) -> Iterator[Event]:
        """Yields events; returns (None, result, applied)."""
        try:
            spec = self.registry.get(call.name)
        except KeyError as exc:
            yield ToolFailed(call_id=call.id, tool=call.name, error=str(exc))
            return None, f"error: {exc}", False

        summary = spec.describe(call.args)

        if (
            self.policy.require_undo_for_destructive
            and spec.effect.value == "destructive"
            and not spec.reversible
        ):
            reason = "destructive tool has no undo handler"
            yield ToolSkipped(call_id=call.id, tool=spec.name, reason=reason)
            return None, f"refused: {reason}", False

        # Dry run: mutating tools describe themselves instead of running.
        if self.dry_run and spec.effect.mutating:
            preview = self._preview(spec, call.args)
            yield DryRunPlanned(
                call_id=call.id, tool=spec.name, display=spec.display, preview=preview
            )
            return None, f"[dry run] {preview}", False

        if self.policy.needs_approval(spec):
            yield ApprovalRequested(
                call_id=call.id,
                tool=spec.name,
                display=spec.display,
                summary=summary,
                effect=spec.effect.value,
                reversible=spec.reversible,
            )
            decision = self._decisions.get(call.id)
            if decision is None:
                decision = Decision(False, "no decision provided")
            yield ApprovalResolved(
                call_id=call.id, approved=decision.approved, reason=decision.reason
            )
            if not decision.approved:
                why = decision.reason or "rejected"
                yield ToolSkipped(call_id=call.id, tool=spec.name, reason=why)
                return None, f"skipped: {why}", False

        yield ToolStarted(
            call_id=call.id,
            tool=spec.name,
            display=spec.display,
            summary=summary,
            effect=spec.effect.value,
        )

        progress_events: list[str] = []

        def progress(message: str) -> None:
            progress_events.append(message)

        started = time.perf_counter()
        try:
            result = self._invoke(spec, call.args, progress)
        except Exception as exc:
            for message in progress_events:
                yield ToolProgress(call_id=call.id, message=message)
            raise ToolExecutionError(call.id, spec.name, exc) from exc

        for message in progress_events:
            yield ToolProgress(call_id=call.id, message=message)

        elapsed = int((time.perf_counter() - started) * 1000)
        yield ToolFinished(
            call_id=call.id, tool=spec.name, result=result, elapsed_ms=elapsed
        )

        if spec.effect.mutating:
            self._journal.append(AppliedEffect(call.id, spec, dict(call.args)))

        return None, result, spec.effect.mutating

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _invoke(
        spec: ToolSpec, args: dict[str, Any], progress: Callable[[str], None]
    ) -> Any:
        import inspect

        if "progress" in inspect.signature(spec.fn).parameters:
            return spec.fn(progress=progress, **args)
        return spec.fn(**args)

    @staticmethod
    def _preview(spec: ToolSpec, args: dict[str, Any]) -> str:
        if spec.preview is None:  # pragma: no cover — decorator forbids this
            return spec.describe(args)
        return spec.preview(**args)

    def _unwind(self) -> Iterator[Event]:
        """Roll back applied effects, newest first."""
        while self._journal:
            effect = self._journal.pop()
            if not effect.spec.reversible:
                yield UndoFailed(
                    call_id=effect.call_id,
                    tool=effect.spec.name,
                    error="no undo handler; effect left in place",
                )
                continue
            try:
                effect.spec.undo(**effect.args)  # type: ignore[misc]
            except Exception as exc:  # noqa: BLE001
                yield UndoFailed(
                    call_id=effect.call_id, tool=effect.spec.name, error=str(exc)
                )
                continue
            self._rolled_back += 1
            yield Undone(
                call_id=effect.call_id,
                tool=effect.spec.name,
                display=effect.spec.display,
            )
