from __future__ import annotations

import pytest

from glasshouse import Effect, Registry, tool


def test_schema_is_generated_from_type_hints(registry):
    spec = registry.get("write_file")
    assert spec.schema == {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
        "additionalProperties": False,
    }


def test_optional_params_are_not_required(registry):
    schema = registry.get("slow_count").schema
    assert schema["required"] == ["n"]
    assert schema["properties"]["n"] == {"type": "integer"}


def test_description_comes_from_the_docstring(registry):
    assert registry.get("list_files").description == "List every known file."


def test_display_name_is_used_not_the_function_name(registry):
    spec = registry.get("delete_file")
    assert spec.describe({"path": "a.txt"}) == "Delete file (path='a.txt')"


def test_mutating_tool_without_preview_is_rejected_at_definition():
    with pytest.raises(ValueError, match="no preview"):

        @tool(display="Nuke", effect=Effect.DESTRUCTIVE)
        def nuke(target: str) -> None:
            """Boom."""


def test_read_tools_need_no_preview():
    @tool(display="Peek", effect=Effect.READ)
    def peek() -> int:
        """Fine."""
        return 1

    assert peek.effect is Effect.READ
    assert not peek.effect.mutating


def test_reversible_reflects_the_undo_handler(registry):
    assert registry.get("delete_file").reversible
    assert not registry.get("shred_file").reversible


def test_duplicate_names_are_rejected():
    @tool(display="One", effect=Effect.READ)
    def dup() -> None:
        """x"""

    reg = Registry.of(dup)
    with pytest.raises(ValueError, match="duplicate"):
        reg.add(dup)


def test_unknown_tool_raises(registry):
    with pytest.raises(KeyError, match="unknown tool"):
        registry.get("nope")


def test_payload_shape_is_provider_neutral(registry):
    payload = registry.as_payload()
    assert len(payload) == len(registry)
    assert set(payload[0]) == {"name", "description", "input_schema"}
