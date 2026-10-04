"""Persistence for the Calendar agent (calendar_events)."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import ContextManager, Protocol

from psycopg_pool import ConnectionPool

from src.calendar_agent.intent import EventDraft
from src.tools.calendar import CalendarEvent, NewEvent

# Arbitrary constants; they only have to be the same in every agent task.
SYNC_LOCK_KEY = 20261004
WRITE_LOCK_KEY = 20261005


class CalendarStore(Protocol):
    """What the service needs from storage; tests use an in-memory fake."""

    def replace_events(self, events: list[CalendarEvent]) -> None: ...

    def list_resolved_requests(self) -> list[tuple[int, int, str, NewEvent]]: ...

    def approval_status(self, approval_id: int) -> str | None: ...

    def mark_request(self, request_id: int, status: str, error: str | None = None) -> None: ...

    def write_lock(self) -> ContextManager[bool]: ...

    def list_pending_intents(self) -> list[tuple[int, str]]: ...

    def create_request(
        self, intent_id: int, draft: EventDraft, approval_title: str, approval_detail: str
    ) -> int: ...

    def fail_intent(self, intent_id: int, error: str) -> None: ...


class PostgresCalendarStore:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def replace_events(self, events: list[CalendarEvent]) -> None:
        """Swap the whole mirror in one transaction, so readers never see it half-filled
        and a failed sync leaves the previous copy in place."""
        with self._pool.connection() as conn, conn.transaction():
            # Two agent tasks syncing at once would collide on the unique key.
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (SYNC_LOCK_KEY,))
            conn.execute("DELETE FROM calendar_events")
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO calendar_events
                      (uid, calendar_name, title, starts_at, ends_at, all_day, location)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (e.uid, e.calendar_name, e.title, e.starts_at, e.ends_at, e.all_day,
                         e.location)
                        for e in events
                    ],
                )

    def list_resolved_requests(self) -> list[tuple[int, int, str, NewEvent]]:
        """Requests whose approval was decided: (request_id, approval_id, decision, event)."""
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT r.id, r.approval_id, a.status,
                       r.event_uid, r.title, r.starts_at, r.ends_at, r.all_day, r.location, r.notes
                FROM calendar_event_requests r
                JOIN approvals a ON a.id = r.approval_id
                WHERE r.status = 'pending_approval' AND a.status IN ('approved', 'skipped')
                ORDER BY r.id
                """
            ).fetchall()
        return [
            (
                int(row[0]),
                int(row[1]),
                str(row[2]),
                NewEvent(
                    uid=row[3], title=row[4], starts_at=row[5], ends_at=row[6],
                    all_day=row[7], location=row[8], notes=row[9],
                ),
            )
            for row in rows
        ]

    def approval_status(self, approval_id: int) -> str | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT status FROM approvals WHERE id = %s", (approval_id,)
            ).fetchone()
        return None if row is None else str(row[0])

    def mark_request(self, request_id: int, status: str, error: str | None = None) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                UPDATE calendar_event_requests
                SET status = %s, error = %s, completed_at = now()
                WHERE id = %s AND status = 'pending_approval'
                """,
                (status, error, request_id),
            )

    @contextmanager
    def write_lock(self) -> Iterator[bool]:
        """Yield True if this task may write. Stops two agent tasks (e.g. during a
        deploy) from handling the same approved request at once."""
        with self._pool.connection() as conn:
            row = conn.execute("SELECT pg_try_advisory_lock(%s)", (WRITE_LOCK_KEY,)).fetchone()
            locked = bool(row and row[0])
            try:
                yield locked
            finally:
                if locked:
                    conn.execute("SELECT pg_advisory_unlock(%s)", (WRITE_LOCK_KEY,))

    def list_pending_intents(self) -> list[tuple[int, str]]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, text FROM calendar_intents
                WHERE status = 'pending' ORDER BY id LIMIT 20
                """
            ).fetchall()
        return [(int(r[0]), str(r[1])) for r in rows]

    def create_request(
        self, intent_id: int, draft: EventDraft, approval_title: str, approval_detail: str
    ) -> int:
        """Approval + request + intent update in one transaction: all or nothing."""
        with self._pool.connection() as conn, conn.transaction():
            approval_id = conn.execute(
                """
                INSERT INTO approvals (agent_id, title, detail)
                VALUES ((SELECT id FROM agents WHERE name = 'calendar'), %s, %s)
                RETURNING id
                """,
                (approval_title, approval_detail),
            ).fetchone()[0]
            request_id = conn.execute(
                """
                INSERT INTO calendar_event_requests
                  (requested_by, title, starts_at, ends_at, all_day, location, reason, approval_id)
                VALUES ((SELECT id FROM agents WHERE name = 'calendar'), %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (draft.title, draft.starts_at, draft.ends_at, draft.all_day, draft.location,
                 "drafted from a sentence typed on the dashboard", approval_id),
            ).fetchone()[0]
            conn.execute(
                """
                UPDATE calendar_intents
                SET status = 'drafted', request_id = %s, completed_at = now()
                WHERE id = %s AND status = 'pending'
                """,
                (request_id, intent_id),
            )
        return int(request_id)

    def fail_intent(self, intent_id: int, error: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                UPDATE calendar_intents
                SET status = 'failed', error = %s, completed_at = now()
                WHERE id = %s AND status = 'pending'
                """,
                (error, intent_id),
            )
