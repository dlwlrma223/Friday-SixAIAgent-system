"""Study agent as a LangGraph: goal -> search queries -> Research -> plan.

The research node goes through ResearchService, so every query the model
writes is logged and passes the PII guard like any other agent's.
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.research.service import ResearchService
from src.study.materials import (
    DEFAULT_LANGUAGE,
    MATERIALS_MAX_TOKENS,
    MATERIALS_SCHEMA,
    Materials,
    ModuleBrief,
    build_materials_message,
    materials_system,
    parse_materials,
    search_queries,
)
from src.study.plan import (
    PLAN_MAX_TOKENS,
    PLAN_SCHEMA,
    PLAN_SYSTEM,
    QUERY_MAX_TOKENS,
    QUERY_SCHEMA,
    QUERY_SYSTEM,
    GoalBrief,
    Plan,
    Source,
    StudyError,
    build_plan_message,
    parse_brief,
    parse_plan,
)
from src.tools.llm import LLMClient

AGENT_NAME = "study"
RESULTS_PER_QUERY = 5
SOURCE_CHARS = 1500
MAX_SOURCES = 15


class StudyState(TypedDict, total=False):
    goal_text: str
    brief: GoalBrief
    sources: list[Source]
    held_queries: int  # queries parked by the PII guard, waiting for approval
    plan: Plan


def gather_sources(
    research: ResearchService, queries: list[str], purpose: str
) -> tuple[list[Source], int]:
    """Run queries through Research. Returns (numbered sources, queries held by the PII guard)."""
    sources: list[Source] = []
    seen: set[str] = set()
    held = 0
    for query in queries:
        outcome = research.request(AGENT_NAME, query, purpose=purpose)
        if outcome.status == "pending_approval":
            held += 1
            continue
        if outcome.response is None:
            continue
        for result in outcome.response.results[:RESULTS_PER_QUERY]:
            url = str(result.url)
            if url in seen or len(sources) >= MAX_SOURCES:
                continue
            seen.add(url)
            sources.append(
                Source(
                    id=len(sources) + 1,
                    title=result.title[:200],
                    url=url,
                    content=result.content[:SOURCE_CHARS],
                )
            )
    return sources, held


def build_study_graph(llm: LLMClient, research: ResearchService) -> CompiledStateGraph:
    def draft_queries(state: StudyState) -> StudyState:
        answer = llm.complete_json(
            QUERY_SYSTEM, f"Goal: {state['goal_text']}", QUERY_SCHEMA, QUERY_MAX_TOKENS
        )
        return {"brief": parse_brief(answer)}

    def research_node(state: StudyState) -> StudyState:
        brief = state["brief"]
        sources, held = gather_sources(research, brief.queries, f"study plan: {brief.title}")
        if not sources:
            if held:
                raise StudyError("搜尋內容被個資檢查擋下，請到上方批准後再送一次，或換個說法。")
            raise StudyError("搜尋沒有找到可用的資料，請換個說法再試。")
        return {"sources": sources, "held_queries": held}

    def write_plan(state: StudyState) -> StudyState:
        sources = state["sources"]
        answer = llm.complete_json(
            PLAN_SYSTEM,
            build_plan_message(state["goal_text"], state["brief"].title, sources),
            PLAN_SCHEMA,
            PLAN_MAX_TOKENS,
        )
        return {"plan": parse_plan(answer, sources)}

    builder = StateGraph(StudyState)
    builder.add_node("draft_queries", draft_queries)
    builder.add_node("research", research_node)
    builder.add_node("write_plan", write_plan)
    builder.add_edge(START, "draft_queries")
    builder.add_edge("draft_queries", "research")
    builder.add_edge("research", "write_plan")
    builder.add_edge("write_plan", END)
    return builder.compile()


class MaterialsState(TypedDict, total=False):
    module: ModuleBrief
    sources: list[Source]
    materials: Materials


def build_materials_graph(
    llm: LLMClient, research: ResearchService, language: str = DEFAULT_LANGUAGE
) -> CompiledStateGraph:
    """One module -> Research -> cards and questions."""
    system = materials_system(language)

    def research_node(state: MaterialsState) -> MaterialsState:
        module = state["module"]
        sources, _ = gather_sources(
            research, search_queries(module), f"study material: {module.title}"
        )
        # No sources is not fatal here: the plan already vetted the subject, and the
        # prompt tells the model to leave out anything it is unsure of.
        return {"sources": sources}

    def write_materials(state: MaterialsState) -> MaterialsState:
        answer = llm.complete_json(
            system,
            build_materials_message(state["module"], state["sources"]),
            MATERIALS_SCHEMA,
            MATERIALS_MAX_TOKENS,
        )
        return {"materials": parse_materials(answer)}

    builder = StateGraph(MaterialsState)
    builder.add_node("research", research_node)
    builder.add_node("write_materials", write_materials)
    builder.add_edge(START, "research")
    builder.add_edge("research", "write_materials")
    builder.add_edge("write_materials", END)
    return builder.compile()
