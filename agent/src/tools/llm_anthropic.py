"""Claude as an LLMClient, through the official Anthropic SDK.

Kept apart from the OpenAI-compatible client in llm.py: Claude is called
with its own SDK and uses structured outputs, so the JSON always matches
the schema the caller asked for.
"""

import json
from typing import Any

from src.tools.llm import LLMError

REQUEST_TIMEOUT_SECONDS = 30.0
# A one-sentence extraction; the answer is a small JSON object.
MAX_OUTPUT_TOKENS = 1024


class AnthropicClient:
    def __init__(self, api_key: str, model: str, client: Any | None = None) -> None:
        self._model = model
        if client is None:
            # Imported lazily so tests and the heartbeat never need the SDK.
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)
        self._client = client

    def __repr__(self) -> str:  # never let the key reach a log line
        return "AnthropicClient(<redacted>)"

    def complete_json(
        self, system: str, user: str, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        import anthropic

        request: dict[str, Any] = {
            "model": self._model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if schema is not None:
            request["output_config"] = {"format": {"type": "json_schema", "schema": schema}}

        # The SDK already retries 429 / 5xx / connection errors twice with backoff.
        # `from None` throughout: SDK exceptions carry the request, headers included.
        try:
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
        return parsed
