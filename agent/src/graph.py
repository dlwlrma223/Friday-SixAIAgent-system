"""LangGraph orchestrator skeleton.

Phase 2 ships one node, `research`. Later phases add their own agent nodes
and route into it; they never call Tavily or ResearchTool directly.
"""

import sys
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.research.service import ResearchOutcome, ResearchService


class State(TypedDict, total=False):
    # Who is asking and what for; written by the calling agent's node.
    agent_name: str
    query: str
    purpose: str | None
    # Written by the research node.
    research: ResearchOutcome | None


def make_research_node(service: ResearchService):
    def research_node(state: State) -> State:
        outcome = service.request(
            state["agent_name"], state["query"], state.get("purpose")
        )
        return {"research": outcome}

    return research_node


def build_graph(service: ResearchService) -> CompiledStateGraph:
    builder = StateGraph(State)
    builder.add_node("research", make_research_node(service))
    builder.add_edge(START, "research")
    builder.add_edge("research", END)
    return builder.compile()


def format_outcome(outcome: ResearchOutcome) -> str:
    if outcome.status == "pending_approval":
        return f"parked for approval (log {outcome.log_id}, approval {outcome.approval_id})"
    if outcome.status == "failed":
        return f"failed (log {outcome.log_id}): {outcome.error}"
    assert outcome.response is not None
    return outcome.response.model_dump_json(indent=2)


def main() -> None:
    """Manual smoke test against real Tavily + DB: python -m src.graph "query"."""
    if len(sys.argv) < 2:
        print('usage: python -m src.graph "query"', file=sys.stderr)
        sys.exit(2)

    from src.db import build_pool
    from src.research.store import PostgresResearchStore
    from src.tools.research import build_research_tool

    pool = build_pool()
    try:
        service = ResearchService(build_research_tool(), PostgresResearchStore(pool))
        initial: State = {
            "agent_name": "research",
            "query": " ".join(sys.argv[1:]),
            "purpose": "manual smoke test",
        }
        final = build_graph(service).invoke(initial)
        print(format_outcome(final["research"]))
    finally:
        pool.close()


if __name__ == "__main__":
    main()
