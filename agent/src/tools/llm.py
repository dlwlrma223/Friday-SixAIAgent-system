"""LLM tool: one JSON-returning chat call against an OpenAI-compatible API.

Provider is configuration, not code: Gemini, Groq, OpenRouter and others all
speak this protocol, so switching is a matter of three env variables. An
optional second provider is tried when the first one fails. A model name
starting with "claude-" is routed to the Anthropic SDK (llm_anthropic.py).
Data boundary: whatever is passed to `complete_json` leaves the system.
Callers decide what goes in; keep it to the minimum the task needs.
"""

import json
import os
import time
from collections.abc import Callable
from typing import Any, Protocol
from urllib.parse import urlsplit

# Primary: Gemini's OpenAI-compatible endpoint (free tier). Fallback: Claude Haiku.
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
# An alias Google keeps pointed at a current model; pinned versions get retired.
DEFAULT_MODEL = "gemini-flash-lite-latest"
DEFAULT_FALLBACK_MODEL = "claude-haiku-4-5"
CLAUDE_PREFIX = "claude-"
ANTHROPIC_KEY_PREFIX = "sk-ant-"
REQUEST_TIMEOUT_SECONDS = 30
# Roomy on purpose: some models spend part of this budget on hidden reasoning.
MAX_OUTPUT_TOKENS = 1024
MAX_ERROR_CHARS = 200
# Free tiers answer "busy" (503) or "slow down" (429) often; one short retry clears most.
RETRY_STATUSES = (429, 503)
RETRY_DELAY_SECONDS = 2


# Called after every successful model call: (model, input_tokens, output_tokens).
UsageSink = Callable[[str, int, int], None]


class LLMError(Exception):
    """Raised when the model can't be reached or answers with something unusable."""


class LLMClient(Protocol):
    """What callers need from a model; tests use a scripted fake."""

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """`schema` (JSON Schema) is enforced by providers that can; callers must
        still validate the answer themselves."""
        ...


class OpenAICompatibleClient:
    def __init__(
        self, base_url: str, api_key: str, model: str, usage_sink: UsageSink | None = None
    ) -> None:
        self._usage_sink = usage_sink
        parts = urlsplit(base_url)
        # The key must never travel in clear text.
        if parts.scheme != "https" or not parts.hostname:
            raise LLMError("LLM_BASE_URL must be an https URL")
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key
        self._model = model

    def __repr__(self) -> str:  # never let the key reach a log line
        return "OpenAICompatibleClient(<redacted>)"

    def _fail(self, detail: str) -> LLMError:
        return LLMError(detail.replace(self._api_key, "***")[:MAX_ERROR_CHARS])

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        # `schema` is unused: JSON mode is the common denominator across these providers.
        # Imported lazily so tests and the heartbeat never need the library.
        import httpx

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": max_tokens or MAX_OUTPUT_TOKENS,
        }
        for attempt in range(2):
            try:
                response = httpx.post(
                    self._url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    follow_redirects=False,
                )
            except Exception as exc:  # httpx raises several classes; callers only need one
                # `from None`: the original traceback can carry request headers.
                raise self._fail(f"model request failed: {exc.__class__.__name__}") from None
            if response.status_code not in RETRY_STATUSES or attempt == 1:
                break
            time.sleep(RETRY_DELAY_SECONDS)

        if response.status_code != 200:
            raise self._fail(f"model answered HTTP {response.status_code}")
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, ValueError):
            raise self._fail("model answer was not valid JSON") from None
        if not isinstance(parsed, dict):
            raise self._fail("model answer was not a JSON object")
        if self._usage_sink:
            usage = body.get("usage") or {}
            self._usage_sink(
                self._model,
                int(usage.get("prompt_tokens") or 0),
                int(usage.get("completion_tokens") or 0),
            )
        return parsed


class FallbackClient:
    """Try each provider in order; the first usable answer wins."""

    def __init__(self, clients: list[LLMClient]) -> None:
        self._clients = clients

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        last: LLMError | None = None
        for client in self._clients:
            try:
                return client.complete_json(system, user, schema, max_tokens)
            except LLMError as exc:
                last = exc
        raise last or LLMError("no LLM provider configured")


def _build_one(
    api_key: str, base_url: str, model: str, usage_sink: UsageSink | None = None
) -> LLMClient:
    if model.startswith(CLAUDE_PREFIX):
        # Guard against a key sitting in the wrong slot: never hand another
        # provider's key to Anthropic.
        if not api_key.startswith(ANTHROPIC_KEY_PREFIX):
            raise LLMError(f"the key configured for {model} is not an Anthropic key")
        from src.tools.llm_anthropic import AnthropicClient

        return AnthropicClient(api_key, model, usage_sink=usage_sink)
    if not base_url:
        raise LLMError(f"a base URL is required for model {model}")
    return OpenAICompatibleClient(base_url, api_key, model, usage_sink)


def resolve_role(role: str, env: dict[str, str] | None = None) -> tuple[str, str, str]:
    """(api_key, base_url, model) for a named job such as "STUDY_PLAN".

    Each job has its own `<ROLE>_API_KEY` / `_BASE_URL` / `_MODEL`, so one job can
    move to a stronger model without touching the others. Anything left empty
    falls back to the general `LLM_*` settings. A Claude model never inherits
    the general key or URL: those belong to another provider.
    """
    env = env if env is not None else dict(os.environ)
    model = env.get(f"{role}_MODEL") or env.get("LLM_MODEL") or DEFAULT_MODEL
    if model.startswith(CLAUDE_PREFIX):
        return env.get(f"{role}_API_KEY") or "", "", model
    api_key = env.get(f"{role}_API_KEY") or env.get("LLM_API_KEY") or ""
    base_url = env.get(f"{role}_BASE_URL") or env.get("LLM_BASE_URL") or DEFAULT_BASE_URL
    return api_key, base_url, model


def build_llm_for(role: str, usage_sink: UsageSink | None = None) -> LLMClient:
    """Build the client for one named job from the environment."""
    api_key, base_url, model = resolve_role(role)
    if not api_key:
        raise LLMError(f"no API key configured for {role} (model {model})")
    return _build_one(api_key, base_url, model, usage_sink)


def build_llm_client() -> LLMClient:
    """Build the real client(s) from the environment."""
    env = os.environ
    clients: list[LLMClient] = []
    if env.get("LLM_API_KEY"):
        model = env.get("LLM_MODEL") or DEFAULT_MODEL
        clients.append(
            _build_one(env["LLM_API_KEY"], env.get("LLM_BASE_URL") or DEFAULT_BASE_URL, model)
        )
    if env.get("LLM_FALLBACK_API_KEY"):
        model = env.get("LLM_FALLBACK_MODEL") or DEFAULT_FALLBACK_MODEL
        try:
            clients.append(
                _build_one(
                    env["LLM_FALLBACK_API_KEY"], env.get("LLM_FALLBACK_BASE_URL") or "", model
                )
            )
        except LLMError:
            # A broken fallback must not take down a working primary.
            if not clients:
                raise
    if not clients:
        raise LLMError("LLM_API_KEY is not set")
    return clients[0] if len(clients) == 1 else FallbackClient(clients)
