"""Persistence for the Research audit trail (research_queries, approvals)."""

from typing import Protocol

from psycopg_pool import ConnectionPool


class ResearchStore(Protocol):
    """What the service needs from storage; tests use an in-memory fake."""

    def load_personal_terms(self) -> list[str]: ...

    def create_log(
        self, agent_name: str, query: str, purpose: str | None, pii_flags: list[str], status: str
    ) -> int: ...

    def create_approval(self, agent_name: str, title: str, detail: str) -> int: ...

    def attach_approval(self, log_id: int, approval_id: int) -> None: ...

    def approval_status(self, approval_id: int) -> str | None: ...

    def mark_sent(
        self, log_id: int, status: str, result_count: int, answer_preview: str | None
    ) -> None: ...

    def mark_failed(self, log_id: int, error: str) -> None: ...

    def get_log(self, log_id: int) -> dict | None: ...


class PostgresResearchStore:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def load_personal_terms(self) -> list[str]:
        with self._pool.connection() as conn:
            rows = conn.execute("SELECT term FROM personal_terms").fetchall()
        return [r[0] for r in rows]

    def create_log(
        self, agent_name: str, query: str, purpose: str | None, pii_flags: list[str], status: str
    ) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO research_queries (agent_id, query, purpose, pii_flags, status)
                VALUES ((SELECT id FROM agents WHERE name = %s), %s, %s, %s, %s)
                RETURNING id
                """,
                (agent_name, query, purpose, pii_flags, status),
            ).fetchone()
        return int(row[0])

    def create_approval(self, agent_name: str, title: str, detail: str) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO approvals (agent_id, title, detail)
                VALUES ((SELECT id FROM agents WHERE name = %s), %s, %s)
                RETURNING id
                """,
                (agent_name, title, detail),
            ).fetchone()
        return int(row[0])

    def attach_approval(self, log_id: int, approval_id: int) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE research_queries SET approval_id = %s WHERE id = %s", (approval_id, log_id)
            )

    def approval_status(self, approval_id: int) -> str | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT status FROM approvals WHERE id = %s", (approval_id,)
            ).fetchone()
        return None if row is None else str(row[0])

    def mark_sent(
        self, log_id: int, status: str, result_count: int, answer_preview: str | None
    ) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                UPDATE research_queries
                SET status = %s, result_count = %s, answer_preview = %s, completed_at = now()
                WHERE id = %s
                """,
                (status, result_count, answer_preview, log_id),
            )

    def mark_failed(self, log_id: int, error: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                UPDATE research_queries
                SET status = 'failed', error = %s, completed_at = now()
                WHERE id = %s
                """,
                (error, log_id),
            )

    def get_log(self, log_id: int) -> dict | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT rq.id, a.name, rq.query, rq.purpose, rq.status, rq.approval_id
                FROM research_queries rq
                LEFT JOIN agents a ON a.id = rq.agent_id
                WHERE rq.id = %s
                """,
                (log_id,),
            ).fetchone()
        if row is None:
            return None
        keys = ("id", "agent_name", "query", "purpose", "status", "approval_id")
        return dict(zip(keys, row))
