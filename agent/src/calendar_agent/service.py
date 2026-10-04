"""Calendar agent: keeps a local mirror of upcoming iCloud events.

Reading is automatic. Writing (added in a later step) always goes through
an approval first.
"""

import os
from dataclasses import dataclass

from src.calendar_agent.store import CalendarStore
from src.tools.calendar import CalendarTool


@dataclass(frozen=True)
class CalendarSettings:
    read_calendars: list[str]  # empty = every calendar that holds events
    write_calendar: str
    sync_days: int
    sync_minutes: int


def _int_env(env: dict[str, str], name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(env.get(name) or default)
    except ValueError:
        return default
    return value if low <= value <= high else default


def load_settings(env: dict[str, str] | None = None) -> CalendarSettings:
    env = env if env is not None else dict(os.environ)
    names = [n.strip() for n in (env.get("CALENDAR_READ") or "").split(",")]
    return CalendarSettings(
        read_calendars=[n for n in names if n],
        write_calendar=(env.get("CALENDAR_WRITE") or "Friday").strip(),
        sync_days=_int_env(env, "CALENDAR_SYNC_DAYS", 30, 1, 366),
        # Floor of 5 minutes: be a polite client, Apple throttles aggressive ones.
        sync_minutes=_int_env(env, "CALENDAR_SYNC_MINUTES", 30, 5, 24 * 60),
    )


@dataclass(frozen=True)
class SyncResult:
    events: int
    calendars: int


class CalendarService:
    def __init__(
        self, tool: CalendarTool, store: CalendarStore, settings: CalendarSettings
    ) -> None:
        self._tool = tool
        self._store = store
        self.settings = settings

    def sync(self) -> SyncResult:
        """Copy upcoming events from iCloud into the DB. Raises CalendarError on
        iCloud problems; the DB is only touched after a complete, successful read."""
        calendars = self.settings.read_calendars or self._tool.list_calendars()
        events = self._tool.upcoming(calendars, self.settings.sync_days)
        self._store.replace_events(events)
        return SyncResult(events=len(events), calendars=len(calendars))
