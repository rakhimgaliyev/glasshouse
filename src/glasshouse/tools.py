"""Tool registry.

A tool is a plain Python function plus metadata the runtime needs to be
*honest* about it: what to call it in front of a human, whether running it
changes anything, how to preview that change without committing, and how to
take it back if a later step fails.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, get_args, get_origin


class Effect(str, Enum):
    """What running this tool does to the world.

    The runtime uses this — not the tool's name — to decide what needs a
    preview, what needs a human, and what needs an undo handler.
    """

    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"

    @property
    def mutating(self) -> bool:
        return self is not Effect.READ


_JSON_TYPES: dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _json_type(annotation: Any) -> str:
    if annotation is inspect.Parameter.empty:
        return "string"
    origin = get_origin(annotation)
    if origin is not None:
        # Optional[X] / X | None -> use X
        args = [a for a in get_args(annotation) if a is not type(None)]
        if origin in (list, tuple, set):
            return "array"
        if origin is dict:
            return "object"
        if len(args) == 1:
            return _json_type(args[0])
        return "string"
    return _JSON_TYPES.get(annotation, "string")


#: Injected by the runtime, never shown to the model.
RESERVED_PARAMS = frozenset({"self", "progress"})


def _schema_from_signature(fn: Callable[..., Any]) -> dict[str, Any]:
    # eval_str resolves the string annotations that `from __future__ import
    # annotations` leaves behind — without it every parameter looks like a str.
    try:
        sig = inspect.signature(fn, eval_str=True)
    except (NameError, TypeError):
        sig = inspect.signature(fn)
    props: dict[str, Any] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        if name in RESERVED_PARAMS:
            continue
        props[name] = {"type": _json_type(param.annotation)}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


@dataclass
class ToolSpec:
    """A registered tool."""

    name: str
    display: str
    description: str
    effect: Effect
    fn: Callable[..., Any]
    schema: dict[str, Any]
    preview: Callable[..., str] | None = None
    undo: Callable[..., Any] | None = None

    @property
    def reversible(self) -> bool:
        return self.undo is not None

    def describe(self, args: dict[str, Any]) -> str:
        """One line a human can read, e.g. 'Delete file (path=/tmp/x)'."""
        if not args:
            return self.display
        rendered = ", ".join(f"{k}={v!r}" for k, v in args.items())
        return f"{self.display} ({rendered})"


def tool(
    *,
    display: str,
    effect: Effect = Effect.READ,
    description: str | None = None,
    preview: Callable[..., str] | None = None,
    undo: Callable[..., Any] | None = None,
    name: str | None = None,
) -> Callable[[Callable[..., Any]], ToolSpec]:
    """Turn a function into a ToolSpec.

    `display` is what the user sees — never the internal function name.
    `preview` returns a human-readable description of what *would* happen,
    and is what dry-run mode calls instead of the real function.
    `undo` receives the same arguments and reverses the effect.
    """

    def decorator(fn: Callable[..., Any]) -> ToolSpec:
        if effect.mutating and preview is None:
            raise ValueError(
                f"tool {fn.__name__!r} has effect={effect.value} but no preview(); "
                "mutating tools must be able to describe themselves before running"
            )
        return ToolSpec(
            name=name or fn.__name__,
            display=display,
            description=description or (inspect.getdoc(fn) or "").split("\n")[0],
            effect=effect,
            fn=fn,
            schema=_schema_from_signature(fn),
            preview=preview,
            undo=undo,
        )

    return decorator


@dataclass
class Registry:
    """A named set of tools."""

    tools: dict[str, ToolSpec] = field(default_factory=dict)

    @classmethod
    def of(cls, *specs: ToolSpec) -> Registry:
        reg = cls()
        for spec in specs:
            reg.add(spec)
        return reg

    def add(self, spec: ToolSpec) -> None:
        if spec.name in self.tools:
            raise ValueError(f"duplicate tool name: {spec.name}")
        self.tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self.tools[name]
        except KeyError:
            raise KeyError(f"unknown tool: {name}") from None

    def __contains__(self, name: object) -> bool:
        return name in self.tools

    def __len__(self) -> int:
        return len(self.tools)

    def as_payload(self) -> list[dict[str, Any]]:
        """Provider-neutral tool definitions."""
        return [
            {"name": s.name, "description": s.description, "input_schema": s.schema}
            for s in self.tools.values()
        ]
