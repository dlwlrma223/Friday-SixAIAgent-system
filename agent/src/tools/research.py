"""Research tool: web search via Tavily, returned as typed results.

Internal tool only — other agents call it, users never do directly.
Data boundary: the query string leaves the system (third-party API).
Callers must go through the guard in research_service, never call this
directly with raw user data.
"""

import os
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, HttpUrl

Topic = Literal["general", "news", "finance"]
SearchDepth = Literal["basic", "advanced"]


class SearchClient(Protocol):
    """Minimal surface of tavily.TavilyClient, so tests can stub it."""

    def search(self, query: str, **kwargs: Any) -> dict[str, Any]: ...


class ResearchError(Exception):
    """Raised when a search cannot be completed (bad key, quota, network)."""


class ResearchResult(BaseModel):
    title: str
    url: HttpUrl
    content: str
    score: float = Field(ge=0.0, le=1.0)


class ResearchResponse(BaseModel):
    query: str
    answer: str | None = None
    results: list[ResearchResult]


class ResearchTool:
    def __init__(self, client: SearchClient) -> None:
        self._client = client

    def run(
        self,
        query: str,
        *,
        max_results: int = 5,
        topic: Topic = "general",
        search_depth: SearchDepth = "basic",
        include_answer: bool = True,
    ) -> ResearchResponse:
        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")
        if not 1 <= max_results <= 20:
            raise ValueError("max_results must be between 1 and 20")

        try:
            raw = self._client.search(
                query,
                max_results=max_results,
                topic=topic,
                search_depth=search_depth,
                include_answer=include_answer,
            )
        except Exception as exc:  # tavily raises several classes; callers only need one
            raise ResearchError(f"search failed: {exc.__class__.__name__}: {exc}") from exc

        results = []
        for item in raw.get("results", []):
            try:
                results.append(ResearchResult.model_validate(item))
            except ValueError:
                # Skip malformed entries instead of failing the whole call.
                continue

        answer = raw.get("answer") or None
        return ResearchResponse(query=query, answer=answer, results=results)


def build_research_tool() -> ResearchTool:
    """Build the real Tavily-backed tool from the environment."""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise ResearchError("TAVILY_API_KEY is not set")

    # Imported lazily so tests and local heartbeat runs never need the SDK.
    from tavily import TavilyClient

    return ResearchTool(TavilyClient(api_key=api_key))
