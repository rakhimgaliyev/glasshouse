"""A FastAPI surface that streams a run over SSE.

Nothing here is required to use the library — it exists to show that the
event stream is the whole API, and that a UI can be built on it without the
runtime knowing a UI exists.

Run: uvicorn glasshouse.server:app --reload
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .events import ApprovalRequested
from .policy import Gate, Policy
from .providers.fake import FakeProvider, calls, says
from .runtime import Session
from .tools import Effect, Registry, tool

app = FastAPI(title="glasshouse", version="0.1.0")


# --------------------------------------------------------------------- #
# a toy toolset so the server is runnable out of the box
# --------------------------------------------------------------------- #

_FILES: dict[str, str] = {"notes.txt": "hello", "tmp/cache.bin": "0101"}
_TRASH: dict[str, str] = {}


@tool(display="List files", effect=Effect.READ)
def list_files() -> list[str]:
    """List every known file."""
    return sorted(_FILES)


@tool(
    display="Delete file",
    effect=Effect.DESTRUCTIVE,
    preview=lambda path: f"would delete {path!r} ({len(_FILES.get(path, ''))} bytes)",
    undo=lambda path: _FILES.update({path: _TRASH.pop(path)}),
)
def delete_file(path: str) -> str:
    """Move a file to the trash."""
    if path not in _FILES:
        raise FileNotFoundError(path)
    _TRASH[path] = _FILES.pop(path)
    return f"deleted {path}"


REGISTRY = Registry.of(list_files, delete_file)


# --------------------------------------------------------------------- #

class RunRequest(BaseModel):
    prompt: str = "clean up the temp files"
    dry_run: bool = False
    gate: str = Gate.ON_MUTATION.value
    auto_approve: bool = False


@dataclass
class _Pending:
    session: Session
    seen: list[str] = field(default_factory=list)


_SESSIONS: dict[str, _Pending] = {}


def _demo_provider() -> FakeProvider:
    return FakeProvider(
        [
            calls(("list_files", {}), text="Let me see what is there."),
            calls(("delete_file", {"path": "tmp/cache.bin"}), text="That one is a cache."),
            says("Done — removed the cache file."),
        ]
    )


def _sse(payload: dict[str, Any]) -> str:
    return f"event: {payload['kind']}\ndata: {json.dumps(payload, default=str)}\n\n"


@app.post("/runs")
def start_run(req: RunRequest) -> StreamingResponse:
    session = Session(
        _demo_provider(),
        REGISTRY,
        policy=Policy(gate=Gate(req.gate)),
        dry_run=req.dry_run,
    )

    def stream() -> Iterator[str]:
        for event in session.run(req.prompt):
            if isinstance(event, ApprovalRequested) and req.auto_approve:
                session.approve(event.call_id, reason="auto_approve=true")
            yield _sse(event.to_dict())

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/tools")
def list_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": s.name,
            "display": s.display,
            "effect": s.effect.value,
            "reversible": s.reversible,
            "description": s.description,
        }
        for s in REGISTRY.tools.values()
    ]


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "tools": str(len(REGISTRY))}


@app.post("/runs/{run_id}/approve/{call_id}")
def approve(run_id: str, call_id: str) -> dict[str, str]:
    pending = _SESSIONS.get(run_id)
    if pending is None:
        raise HTTPException(404, "unknown run")
    pending.session.approve(call_id)
    return {"status": "approved"}
