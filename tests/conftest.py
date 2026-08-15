from __future__ import annotations

import pytest

from glasshouse import Effect, Registry, tool


@pytest.fixture
def world() -> dict[str, dict[str, str]]:
    return {"files": {"a.txt": "aaa", "b.txt": "bb"}, "trash": {}}


@pytest.fixture
def registry(world) -> Registry:
    files, trash = world["files"], world["trash"]

    @tool(display="List files", effect=Effect.READ)
    def list_files() -> list[str]:
        """List every known file."""
        return sorted(files)

    @tool(display="Read file", effect=Effect.READ)
    def read_file(path: str) -> str:
        """Return a file's contents."""
        return files[path]

    @tool(
        display="Write file",
        effect=Effect.WRITE,
        preview=lambda path, content: f"would write {len(content)} bytes to {path!r}",
    )
    def write_file(path: str, content: str) -> str:
        """Create or overwrite a file."""
        files[path] = content
        return f"wrote {path}"

    @tool(
        display="Delete file",
        effect=Effect.DESTRUCTIVE,
        preview=lambda path: f"would delete {path!r}",
        undo=lambda path: files.update({path: trash.pop(path)}),
    )
    def delete_file(path: str) -> str:
        """Move a file to the trash."""
        if path not in files:
            raise FileNotFoundError(path)
        trash[path] = files.pop(path)
        return f"deleted {path}"

    @tool(
        display="Shred file",
        effect=Effect.DESTRUCTIVE,
        preview=lambda path: f"would shred {path!r}",
    )
    def shred_file(path: str) -> str:
        """Delete a file with no way back."""
        files.pop(path, None)
        return f"shredded {path}"

    @tool(display="Slow count", effect=Effect.READ)
    def slow_count(n: int, progress=None) -> int:
        """Count to n, reporting progress."""
        for i in range(n):
            if progress:
                progress(f"step {i + 1}/{n}")
        return n

    return Registry.of(
        list_files, read_file, write_file, delete_file, shred_file, slow_count
    )


def kinds(events) -> list[str]:
    return [e.kind for e in events]


def first(events, cls):
    return next(e for e in events if isinstance(e, cls))


def only(events, cls) -> list:
    return [e for e in events if isinstance(e, cls)]
