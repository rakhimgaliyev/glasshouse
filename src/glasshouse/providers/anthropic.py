"""Claude provider.

Optional: the package does not depend on `anthropic`, and nothing in the
test suite imports this module. Install with ``pip install glasshouse[anthropic]``.
"""

from __future__ import annotations

from typing import Any

from .base import Completion, Provider, ToolCall

DEFAULT_MODEL = "claude-opus-5"


class AnthropicProvider(Provider):
    """Translate the runtime's neutral messages to the Messages API and back."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 16000,
        system: str | None = None,
        client: Any | None = None,
        thinking: dict[str, Any] | None = None,
    ) -> None:
        if client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover
                raise ImportError(
                    "the anthropic package is required: pip install 'glasshouse[anthropic]'"
                ) from exc
            client = anthropic.Anthropic()
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.system = system
        # Adaptive thinking: Claude decides how much to think. budget_tokens is
        # rejected on this model family.
        self.thinking = thinking if thinking is not None else {"type": "adaptive"}

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Completion:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": self._to_anthropic(messages),
            "thinking": self.thinking,
        }
        if tools:
            kwargs["tools"] = tools
        if self.system:
            kwargs["system"] = self.system

        response = self.client.messages.create(**kwargs)

        # stop_details is populated only for refusals; guard before reading.
        if getattr(response, "stop_reason", None) == "refusal":
            detail = getattr(response, "stop_details", None)
            category = getattr(detail, "category", None) or "unspecified"
            return Completion(text=f"[refused: {category}]")

        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in response.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, args=dict(block.input)))

        return Completion(text="\n".join(text_parts).strip(), tool_calls=calls)

    # ------------------------------------------------------------------ #

    @staticmethod
    def _to_anthropic(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for msg in messages:
            if msg.get("tool_results"):
                out.append(
                    {
                        "role": "user",
                        # All results in ONE message — splitting them trains the
                        # model to stop making parallel calls.
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": r["tool_call_id"],
                                "content": str(r["content"]),
                            }
                            for r in msg["tool_results"]
                        ],
                    }
                )
            elif msg.get("tool_calls"):
                blocks: list[dict[str, Any]] = []
                if msg.get("content"):
                    blocks.append({"type": "text", "text": msg["content"]})
                blocks.extend(
                    {
                        "type": "tool_use",
                        "id": c["id"],
                        "name": c["name"],
                        "input": c["args"],
                    }
                    for c in msg["tool_calls"]
                )
                out.append({"role": "assistant", "content": blocks})
            else:
                out.append({"role": msg["role"], "content": msg["content"]})
        return out
