"""Persistence for the Study agent (study_goals, study_modules, llm_usage)."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import ContextManager, Protocol

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from src.study.materials import Materials, ModuleBrief
from src.study.plan import Plan, Source

# Arbitrary constant; only has to be the same in every agent task.
STUDY_LOCK_KEY = 20261006


class StudyStore(Protocol):
    """What the service needs from storage; tests use an in-memory fake."""

    def list_pending_goals(self) -> list[tuple[int, str]]: ...

    def save_plan(self, goal_id: int, subject: str, plan: Plan, sources: list[Source]) -> None: ...

    def fail_goal(self, goal_id: int, error: str) -> None: ...

    def record_usage(
        self, purpose: str, model: str, input_tokens: int, output_tokens: int
    ) -> None: ...

    def usage_calls_today(self, purpose_prefix: str) -> int: ...

    def lock(self) -> ContextManager[bool]: ...

    def list_pending_modules(self) -> list[ModuleBrief]: ...

    def save_materials(
        self, module_id: int, materials: Materials, sources: list[Source]
    ) -> None: ...

    def fail_materials(self, module_id: int, error: str) -> None: ...


class PostgresStudyStore:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def list_pending_goals(self) -> list[tuple[int, str]]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, request_text FROM study_goals
                WHERE status = 'pending' ORDER BY id LIMIT 5
                """
            ).fetchall()
        return [(int(r[0]), str(r[1])) for r in rows]

    def save_plan(self, goal_id: int, subject: str, plan: Plan, sources: list[Source]) -> None:
        """Goal + modules in one transaction: a plan is never half-saved."""
        with self._pool.connection() as conn, conn.transaction():
            subject_id = conn.execute(
                """
                INSERT INTO subjects (name) VALUES (%s)
                ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """,
                (subject,),
            ).fetchone()[0]
            updated = conn.execute(
                """
                UPDATE study_goals
                SET status = 'planned', subject_id = %s, title = %s, overview = %s, facts = %s,
                    total_weeks = %s, sources = %s, completed_at = now()
                WHERE id = %s AND status = 'pending'
                """,
                (
                    subject_id,
                    plan.title,
                    plan.overview,
                    Jsonb([f.model_dump() for f in plan.facts]),
                    plan.total_weeks,
                    # Page text is not stored: only where the plan came from.
                    Jsonb([{"id": s.id, "title": s.title, "url": s.url} for s in sources]),
                    goal_id,
                ),
            )
            if updated.rowcount != 1:
                return
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO study_modules
                      (goal_id, position, title, summary, topics, est_hours, week, source_ids)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (goal_id, position, m.title, m.summary, m.topics, m.est_hours, m.week,
                         m.source_ids)
                        for position, m in enumerate(plan.modules, start=1)
                    ],
                )

    def fail_goal(self, goal_id: int, error: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                UPDATE study_goals SET status = 'failed', error = %s, completed_at = now()
                WHERE id = %s AND status = 'pending'
                """,
                (error, goal_id),
            )

    def record_usage(
        self, purpose: str, model: str, input_tokens: int, output_tokens: int
    ) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO llm_usage (purpose, model, input_tokens, output_tokens)
                VALUES (%s, %s, %s, %s)
                """,
                (purpose, model, input_tokens, output_tokens),
            )

    def usage_calls_today(self, purpose_prefix: str) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT count(*) FROM llm_usage
                WHERE purpose LIKE %s AND created_at > now() - interval '24 hours'
                """,
                (purpose_prefix + "%",),
            ).fetchone()
        return int(row[0]) if row else 0

    @contextmanager
    def lock(self) -> Iterator[bool]:
        """Yield True if this task may plan. One planner at a time, across agent tasks."""
        with self._pool.connection() as conn:
            row = conn.execute("SELECT pg_try_advisory_lock(%s)", (STUDY_LOCK_KEY,)).fetchone()
            locked = bool(row and row[0])
            try:
                yield locked
            finally:
                if locked:
                    conn.execute("SELECT pg_advisory_unlock(%s)", (STUDY_LOCK_KEY,))

    def list_pending_modules(self) -> list[ModuleBrief]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT m.id, COALESCE(g.title, g.request_text), m.title, COALESCE(m.summary, ''),
                       m.topics
                FROM study_modules m JOIN study_goals g ON g.id = m.goal_id
                WHERE m.materials_status = 'pending'
                ORDER BY m.id LIMIT 5
                """
            ).fetchall()
        return [
            ModuleBrief(module_id=r[0], goal_title=r[1], title=r[2], summary=r[3], topics=r[4])
            for r in rows
        ]

    def save_materials(
        self, module_id: int, materials: Materials, sources: list[Source]
    ) -> None:
        """Replace the module's cards and questions in one transaction."""
        with self._pool.connection() as conn, conn.transaction():
            updated = conn.execute(
                """
                UPDATE study_modules
                SET materials_status = 'ready', materials_error = NULL, materials_sources = %s
                WHERE id = %s AND materials_status = 'pending'
                """,
                (Jsonb([{"id": s.id, "title": s.title, "url": s.url} for s in sources]), module_id),
            )
            if updated.rowcount != 1:
                return
            # Regenerating replaces the old set (and, by cascade, its attempts).
            conn.execute("DELETE FROM study_cards WHERE module_id = %s", (module_id,))
            conn.execute("DELETE FROM study_questions WHERE module_id = %s", (module_id,))
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO study_cards (module_id, position, front, back) "
                    "VALUES (%s, %s, %s, %s)",
                    [
                        (module_id, i, c.front, c.back)
                        for i, c in enumerate(materials.cards, start=1)
                    ],
                )
                cur.executemany(
                    "INSERT INTO study_questions "
                    "(module_id, position, question, options, correct_index, explanation) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    [
                        (module_id, i, q.question, Jsonb(q.options), q.correct_index, q.explanation)
                        for i, q in enumerate(materials.questions, start=1)
                    ],
                )

    def fail_materials(self, module_id: int, error: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                UPDATE study_modules SET materials_status = 'failed', materials_error = %s
                WHERE id = %s AND materials_status = 'pending'
                """,
                (error, module_id),
            )
