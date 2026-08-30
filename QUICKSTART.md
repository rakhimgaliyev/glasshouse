# Quickstart

## Run it

```bash
uv venv && uv pip install -e ".[dev,server]"

make test    # 45 tests, no network, no API key
make demo    # one scenario through all three modes
make serve   # SSE endpoint on :8000
```

## Use it in your own code

Three things: declare tools with an effect, hand them to a Session, iterate.

```python
from glasshouse import (
    ApprovalRequested, Effect, FakeProvider, Registry, Session,
    calls, says, tool,
)

DB = {"users": 3}

@tool(display="Count users", effect=Effect.READ)
def count_users() -> int:
    """How many users are in the database."""
    return DB["users"]

@tool(
    display="Drop table",
    effect=Effect.DESTRUCTIVE,
    preview=lambda table: f"would drop {table!r} ({DB.get(table, 0)} rows)",
)
def drop_table(table: str) -> str:
    """Delete a table."""
    DB.pop(table, None)
    return f"dropped {table}"


registry = Registry.of(count_users, drop_table)

provider = FakeProvider([
    calls(("count_users", {}), text="Checking first."),
    calls(("drop_table", {"table": "users"}), text="Safe to drop."),
    says("Done."),
])

session = Session(provider, registry)

for event in session.run("clean the database"):
    if isinstance(event, ApprovalRequested):
        print(f"GATE: {event.summary}  [{event.effect}]")
        session.reject(event.call_id, reason="not dropping the users table")
```

```
GATE: Drop table (table='users')  [destructive]
DB after: {'users': 3}     # the agent wanted it gone; the gate said no
```

## Switch to a real model

Same code, one line changed:

```python
from glasshouse.providers.anthropic import AnthropicProvider

session = Session(AnthropicProvider(), registry)
```

Needs `pip install 'glasshouse[anthropic]'` and `ANTHROPIC_API_KEY`.
Everything else — gating, dry run, rollback — behaves identically.

## The knobs

```python
Session(
    provider,
    registry,
    policy=Policy(gate=Gate.ON_MUTATION),  # NEVER / ON_DESTRUCTIVE / ON_MUTATION / ALWAYS
    dry_run=False,      # True: mutations report what they would do, and stop there
    max_turns=12,       # ceiling on the agent loop
    auto_undo=True,     # roll applied effects back when a later step raises
)
```

`Policy(require_undo_for_destructive=True)` refuses to run a destructive tool
that has no `undo` handler at all.

## What to read first

`src/glasshouse/runtime.py` — the loop. Everything interesting is there:
the approval gate, dry-run interception, the effect journal, and the unwind.
About 250 lines.
