"""A full run, printed. No API key, no network, no cost.

    python examples/demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from glasshouse import (
    ApprovalRequested,
    DryRunPlanned,
    Effect,
    FakeProvider,
    Gate,
    Policy,
    Registry,
    Session,
    ToolFailed,
    Undone,
    calls,
    says,
    tool,
)

FILES = {"notes.txt": "hello", "tmp/cache.bin": "0101", "tmp/old.log": "..."}
TRASH: dict[str, str] = {}


@tool(display="List files", effect=Effect.READ)
def list_files() -> list[str]:
    """List every known file."""
    return sorted(FILES)


@tool(
    display="Delete file",
    effect=Effect.DESTRUCTIVE,
    preview=lambda path: f"would delete {path!r} ({len(FILES.get(path, ''))} bytes)",
    undo=lambda path: FILES.update({path: TRASH.pop(path)}),
)
def delete_file(path: str) -> str:
    """Move a file to the trash."""
    if path not in FILES:
        raise FileNotFoundError(path)
    TRASH[path] = FILES.pop(path)
    return f"deleted {path}"


REGISTRY = Registry.of(list_files, delete_file)


def script():
    return [
        calls(("list_files", {}), text="Let me look at what is there."),
        calls(
            ("delete_file", {"path": "tmp/cache.bin"}),
            ("delete_file", {"path": "tmp/old.log"}),
            text="Both of those are disposable.",
        ),
        says("Cleaned up two temp files."),
    ]


def show(title: str, session: Session, prompt: str, *, approve_all: bool = True) -> None:
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")
    for event in session.run(prompt):
        if isinstance(event, ApprovalRequested):
            mark = "APPROVE" if approve_all else "REJECT"
            print(f"  ? {event.summary}   [{event.effect}, "
                  f"{'reversible' if event.reversible else 'NOT reversible'}] -> {mark}")
            (session.approve if approve_all else session.reject)(event.call_id)
            continue
        if isinstance(event, DryRunPlanned):
            print(f"  ~ {event.preview}")
            continue
        if isinstance(event, Undone):
            print(f"  < rolled back: {event.display}")
            continue
        if isinstance(event, ToolFailed):
            print(f"  ! {event.tool}: {event.error}")
            continue
        print(f"  · {event.kind}: {getattr(event, 'summary', '') or getattr(event, 'text', '')}")


def main() -> None:
    global FILES, TRASH

    FILES = {"notes.txt": "hello", "tmp/cache.bin": "0101", "tmp/old.log": "..."}
    show(
        "1. DRY RUN — nothing is touched",
        Session(FakeProvider(script()), REGISTRY, dry_run=True),
        "clean up the temp files",
    )
    print(f"  files after: {sorted(FILES)}")

    FILES = {"notes.txt": "hello", "tmp/cache.bin": "0101", "tmp/old.log": "..."}
    TRASH = {}
    show(
        "2. GATED — every mutation asks first",
        Session(FakeProvider(script()), REGISTRY, policy=Policy(gate=Gate.ON_MUTATION)),
        "clean up the temp files",
    )
    print(f"  files after: {sorted(FILES)}")

    FILES = {"notes.txt": "hello", "tmp/cache.bin": "0101"}  # old.log missing -> boom
    TRASH = {}
    show(
        "3. FAILURE MID-CHAIN — the first delete is rolled back",
        Session(FakeProvider(script()), REGISTRY, policy=Policy(gate=Gate.NEVER)),
        "clean up the temp files",
    )
    print(f"  files after: {sorted(FILES)}   (cache.bin restored)")


if __name__ == "__main__":
    main()
