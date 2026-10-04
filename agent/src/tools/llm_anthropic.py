"""Claude as an LLMClient, through the official Anthropic SDK.

Kept apart from the OpenAI-compatible client in llm.py: Claude is called
with its own SDK and uses structured outputs, so the JSON always matches
the schema the caller asked for.
"""

import json
from typing import Any

from src.tools.llm import LLMError, UsageSink

# Long answers (a study plan, a chapter of notes) take a while to write.
REQUEST_TIMEOUT_SECONDS = 300.0
# Default for small extractions; callers writing long documents pass their own.
MAX_OUTPUT_TOKENS = 1024
# Models whose safety classifiers can decline a request. For these, ask the API
# to re-run a declined request on Anthropic's recommended fallback model.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MODELS_WITH_FALLBACKS = ("claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5")


class AnthropicClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        client: Any | None = None,
        usage_sink: UsageSink | None = None,
    ) -> None:
        self._model = model
        self._usage_sink = usage_sink
        if client is None:
            # Imported lazily so tests and the heartbeat never need the SDK.
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)
        self._client = client

    def __repr__(self) -> str:  # never let the key reach a log line
        return "AnthropicClient(<redacted>)"

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        import anthropic

        request: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens or MAX_OUTPUT_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if schema is not None:
            request["output_config"] = {"format": {"type": "json_schema", "schema": schema}}

        # The SDK already retries 429 / 5xx / connection errors twice with backoff.
        # `from None` throughout: SDK exceptions carry the request, headers included.
        try:
            if self._model.startswith(MODELS_WITH_FALLBACKS):
                response = self._client.beta.messages.create(
                    **request, betas=[FALLBACK_BETA], fallbacks="default"
                )
            else:
                response = self._client.messages.create(**request)
        except anthropic.AuthenticationError:
            raise LLMError("claude rejected the API key (HTTP 401)") from None
        except anthropic.NotFoundError:
            raise LLMError("claude model not found (HTTP 404)") from None
        except anthropic.RateLimitError:
            raise LLMError("claude rate limit reached (HTTP 429)") from None
        except anthropic.APIStatusError as exc:
            raise LLMError(f"claude answered HTTP {exc.status_code}") from None
        except anthropic.APIConnectionError:
            raise LLMError("claude request failed: connection error") from None

        if response.stop_reason != "end_turn":
            raise LLMError(f"claude stopped early ({response.stop_reason})")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            parsed = json.loads(text)
        except ValueError:
            raise LLMError("claude answer was not valid JSON") from None
        if not isinstance(parsed, dict):
            raise LLMError("claude answer was not a JSON object")
        if self._usage_sink:
            usage = getattr(response, "usage", None)
            self._usage_sink(
                self._model,
                int(getattr(usage, "input_tokens", 0) or 0),
                int(getattr(usage, "output_tokens", 0) or 0),
            )
        return parsed
