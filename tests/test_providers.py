"""The Anthropic provider is tested against a stub client — no network, no key."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from glasshouse.providers.anthropic import DEFAULT_MODEL, AnthropicProvider


class StubClient:
    def __init__(self, response) -> None:
        self._response = response
        self.messages = SimpleNamespace(create=self._create)
        self.seen: dict = {}

    def _create(self, **kwargs):
        self.seen = kwargs
        return self._response


def block(**kw):
    return SimpleNamespace(**kw)


def response(content, stop_reason="end_turn", stop_details=None):
    return SimpleNamespace(
        content=content, stop_reason=stop_reason, stop_details=stop_details
    )


def test_text_response_is_normalised():
    client = StubClient(response([block(type="text", text="hello")]))
    out = AnthropicProvider(client=client).complete([{"role": "user", "content": "hi"}], [])
    assert out.text == "hello"
    assert not out.wants_tools


def test_tool_use_blocks_become_tool_calls():
    client = StubClient(
        response(
            [
                block(type="text", text="looking"),
                block(type="tool_use", id="tu_1", name="read_file", input={"path": "a"}),
            ],
            stop_reason="tool_use",
        )
    )
    out = AnthropicProvider(client=client).complete([{"role": "user", "content": "hi"}], [])
    assert out.text == "looking"
    assert [(c.id, c.name, c.args) for c in out.tool_calls] == [
        ("tu_1", "read_file", {"path": "a"})
    ]


def test_refusal_is_handled_not_crashed():
    client = StubClient(
        response([], stop_reason="refusal", stop_details=SimpleNamespace(category="cyber"))
    )
    out = AnthropicProvider(client=client).complete([{"role": "user", "content": "hi"}], [])
    assert out.text == "[refused: cyber]"
    assert not out.wants_tools


def test_defaults_are_current():
    client = StubClient(response([block(type="text", text="x")]))
    AnthropicProvider(client=client).complete([{"role": "user", "content": "hi"}], [])
    assert client.seen["model"] == DEFAULT_MODEL == "claude-opus-5"
    # Adaptive thinking; budget_tokens is rejected on this model family.
    assert client.seen["thinking"] == {"type": "adaptive"}
    assert "budget_tokens" not in str(client.seen)


def test_tool_results_are_translated_into_one_user_message():
    client = StubClient(response([block(type="text", text="ok")]))
    provider = AnthropicProvider(client=client)
    provider.complete(
        [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": "working",
                "tool_calls": [{"id": "t1", "name": "f", "args": {"x": 1}}],
            },
            {
                "role": "user",
                "tool_results": [
                    {"tool_call_id": "t1", "content": "done"},
                    {"tool_call_id": "t2", "content": "also done"},
                ],
            },
        ],
        [],
    )
    sent = client.seen["messages"]
    assert sent[1]["content"][0] == {"type": "text", "text": "working"}
    assert sent[1]["content"][1]["type"] == "tool_use"
    assert len(sent[2]["content"]) == 2, "results must share one message"
    assert sent[2]["content"][0]["type"] == "tool_result"


def test_system_prompt_is_passed_through():
    client = StubClient(response([block(type="text", text="x")]))
    AnthropicProvider(client=client, system="be terse").complete(
        [{"role": "user", "content": "hi"}], []
    )
    assert client.seen["system"] == "be terse"


def test_fake_provider_rejects_an_empty_script():
    from glasshouse import FakeProvider

    with pytest.raises(ValueError):
        FakeProvider([])
