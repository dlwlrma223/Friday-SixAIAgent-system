"""Study agent: turns a learning goal into a researched study plan, and writes
cards and quiz questions for a module when asked."""

from dataclasses import dataclass
from typing import Literal

from langgraph.graph.state import CompiledStateGraph

from src.study.plan import StudyError
from src.study.store import StudyStore
from src.tools.llm import LLMError

USAGE_PREFIX = "study"
DEFAULT_DAILY_CALLS = 40
LIMIT_REACHED = (
    "今天 Study agent 的 AI 使用次數已達上限（{limit} 次），"
    "請明天再試或調高 STUDY_DAILY_CALLS。"
)
LLM_UNAVAILABLE = "AI 暫時連不上，請稍後再試。"
UNEXPECTED = "處理時發生未預期的錯誤，請再試一次。"


@dataclass(frozen=True)
class GoalOutcome:
    goal_id: int
    status: Literal["planned", "failed"]
    modules: int = 0


@dataclass(frozen=True)
class MaterialsOutcome:
    module_id: int
    status: Literal["ready", "failed"]
    cards: int = 0
    questions: int = 0


class StudyService:
    def __init__(
        self,
        graph: CompiledStateGraph,
        store: StudyStore,
        daily_calls: int = DEFAULT_DAILY_CALLS,
        materials_graph: CompiledStateGraph | None = None,
    ) -> None:
        self._graph = graph
        self._materials_graph = materials_graph
        self._store = store
        self._daily_calls = daily_calls

    def process_goals(self) -> list[GoalOutcome]:
        """Plan every goal that is waiting. Safe to call any time."""
        outcomes: list[GoalOutcome] = []
        with self._store.lock() as locked:
            if not locked:
                return outcomes
            for goal_id, text in self._store.list_pending_goals():
                outcomes.append(self._plan(goal_id, text))
        return outcomes

    def _plan(self, goal_id: int, text: str) -> GoalOutcome:
        # Spending guard: checked per goal, so a runaway loop stops within one plan.
        if self._store.usage_calls_today(USAGE_PREFIX) >= self._daily_calls:
            self._store.fail_goal(goal_id, LIMIT_REACHED.format(limit=self._daily_calls))
            return GoalOutcome(goal_id, "failed")
        try:
            final = self._graph.invoke({"goal_text": text})
        except StudyError as exc:
            self._store.fail_goal(goal_id, str(exc))
            return GoalOutcome(goal_id, "failed")
        except LLMError:
            # Provider details stay in the agent log, not on the dashboard.
            self._store.fail_goal(goal_id, LLM_UNAVAILABLE)
            return GoalOutcome(goal_id, "failed")
        except Exception:
            self._store.fail_goal(goal_id, UNEXPECTED)
            raise

        plan = final["plan"]
        self._store.save_plan(goal_id, final["brief"].subject, plan, final["sources"])
        return GoalOutcome(goal_id, "planned", modules=len(plan.modules))

    def process_materials(self) -> list[MaterialsOutcome]:
        """Write cards and questions for every module waiting. Safe to call any time."""
        outcomes: list[MaterialsOutcome] = []
        if self._materials_graph is None:
            return outcomes
        with self._store.lock() as locked:
            if not locked:
                return outcomes
            for module in self._store.list_pending_modules():
                outcomes.append(self._write_materials(module))
        return outcomes

    def _write_materials(self, module) -> MaterialsOutcome:
        module_id = module.module_id
        if self._store.usage_calls_today(USAGE_PREFIX) >= self._daily_calls:
            self._store.fail_materials(module_id, LIMIT_REACHED.format(limit=self._daily_calls))
            return MaterialsOutcome(module_id, "failed")
        try:
            final = self._materials_graph.invoke({"module": module})
        except StudyError as exc:
            self._store.fail_materials(module_id, str(exc))
            return MaterialsOutcome(module_id, "failed")
        except LLMError:
            self._store.fail_materials(module_id, LLM_UNAVAILABLE)
            return MaterialsOutcome(module_id, "failed")
        except Exception:
            self._store.fail_materials(module_id, UNEXPECTED)
            raise

        materials = final["materials"]
        self._store.save_materials(module_id, materials, final["sources"])
        return MaterialsOutcome(
            module_id, "ready", cards=len(materials.cards), questions=len(materials.questions)
        )
