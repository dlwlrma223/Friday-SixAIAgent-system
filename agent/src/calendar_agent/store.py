"""Persistence for the Calendar agent (calendar_events)."""

from typing import Protocol

from psycopg_pool import ConnectionPool

from src.tools.calendar import CalendarEvent

# Arbitrary constant; only has to be the same in every agent task.
SYNC_LOCK_KEY = 20261004


class CalendarStore(Protocol):
    """What the service needs from storage; tests use an in-memory fake."""

    def replace_events(self, events: list[CalendarEvent]) -> None: ...


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
