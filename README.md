# glasshouse

**See what your agent is doing — before it does it.**

A small Python runtime that wraps an LLM agent loop and makes every tool call
*visible*, *previewable*, *gated*, and *reversible*.

Most agent libraries treat the loop as plumbing: the model asks for tools, they
run, you get an answer. That is fine until an agent does something in production
that nobody sanctioned and nobody can undo. This library is the loop with the
lid off.

```python
from glasshouse import Session, Registry, Policy, Gate, ApprovalRequested

session = Session(provider, registry, policy=Policy(gate=Gate.ON_MUTATION))

for event in session.run("clean up the temp files"):
    if isinstance(event, ApprovalRequested):
        print(event.summary)          # "Delete file (path='tmp/cache.bin')"
        session.approve(event.call_id)
```

## What it does

| | |
|---|---|
| **Visible** | Every decision is an event — tool started, progress, finished, failed, skipped. Tools carry a human-readable `display` name, never the internal function name. |
| **Previewable** | `dry_run=True` runs the whole agent without touching anything. Mutating tools call their `preview()` and report what *would* happen. |
| **Gated** | Mutating or destructive calls stop and wait for a human. The policy decides which, not the tool. |
| **Reversible** | Applied effects go in a journal. If a later step fails, they are undone newest-first. |

## Why the effect annotation matters

The runtime never guesses from a tool's name what it does. Each tool declares it:

```python
@tool(display="List files", effect=Effect.READ)
def list_files() -> list[str]:
    ...

@tool(
    display="Delete file",
    effect=Effect.DESTRUCTIVE,
    preview=lambda path: f"would delete {path!r}",
    undo=lambda path: restore(path),
)
def delete_file(path: str) -> str:
    ...
```

`Effect` drives everything downstream: what dry-run intercepts, what the policy
gates, what goes in the undo journal. A mutating tool without a `preview` is a
`ValueError` at import time — if a tool cannot describe itself before running,
you cannot honestly ask a human to approve it.

## The three modes

Run `python examples/demo.py` to see all of them. Abridged output:

```
1. DRY RUN — nothing is touched
  ~ would delete 'tmp/cache.bin' (4 bytes)
  ~ would delete 'tmp/old.log' (3 bytes)
  files after: ['notes.txt', 'tmp/cache.bin', 'tmp/old.log']

2. GATED — every mutation asks first
  ? Delete file (path='tmp/cache.bin')   [destructive, reversible] -> APPROVE
  ? Delete file (path='tmp/old.log')     [destructive, reversible] -> APPROVE
  files after: ['notes.txt']

3. FAILURE MID-CHAIN — the first delete is rolled back
  ! delete_file: 'tmp/old.log'
  < rolled back: Delete file
  files after: ['notes.txt', 'tmp/cache.bin']   (cache.bin restored)
```

## Providers

The runtime never imports a vendor SDK. It asks a `Provider` for the next turn
and gets a normalised `Completion` back:

```python
class Provider(Protocol):
    def complete(self, messages, tools) -> Completion: ...
```

Two ship with the package:

- **`FakeProvider`** — a scripted provider. Every test and the demo run on it:
  no API key, no network, no cost, and the agent behaves identically every time.
  That reproducibility is the only way to write assertions about an agent loop
  that mean anything.
- **`AnthropicProvider`** — Claude via the Messages API (`claude-opus-5`,
  adaptive thinking). Optional dependency; nothing in the test suite imports it.

## Install

```bash
uv venv && uv pip install -e ".[dev,server]"
make test      # 20 tests, no network
make demo      # the three modes above
make serve     # SSE endpoint at POST /runs
```

## Streaming

Events are dataclasses with a `kind` and a `to_dict()`, which makes an SSE
endpoint about ten lines (`glasshouse/server.py`):

```
event: approval_requested
data: {"kind": "approval_requested", "call_id": "call_0",
       "display": "Delete file", "effect": "destructive", "reversible": true}
```

## Layout

```
src/glasshouse/
  tools.py           @tool, Effect, Registry — schema generated from type hints
  events.py          every event the runtime can emit
  policy.py          Gate: NEVER / ON_DESTRUCTIVE / ON_MUTATION / ALWAYS
  runtime.py         the loop: gating, dry-run, journal, unwind
  server.py          FastAPI + SSE (optional)
  providers/
    base.py          Provider protocol, Completion, ToolCall
    fake.py          scripted provider — what the tests run on
    anthropic.py     Claude (optional dependency)
```

## Status

Early. The core loop, gating, dry-run and rollback are implemented and tested.
Not yet: async tools, streaming partial tool results, nested/sub-agent runs,
persistence of the journal across processes.

## Licence

MIT
