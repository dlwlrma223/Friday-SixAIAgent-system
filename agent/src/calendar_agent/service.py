"""Calendar agent: keeps a local mirror of upcoming iCloud events.

Reading is automatic. Writing only ever happens for a request whose approval
row says `approved`, and only into the one configured calendar.
"""

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from src.calendar_agent.intent import IntentError, describe_draft, parse_intent
from src.calendar_agent.store import CalendarStore
from src.tools.calendar import CalendarError, CalendarTool
from src.tools.llm import LLMClient, LLMError

LLM_MISSING = "AI 尚未設定（缺少 LLM_API_KEY），這句話沒有被處理。"
LLM_UNAVAILABLE = "AI 暫時連不上，請稍後再試。"


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


@dataclass(frozen=True)
class WriteOutcome:
    request_id: int
    status: Literal["written", "skipped", "failed"]


@dataclass(frozen=True)
class IntentOutcome:
    intent_id: int
    status: Literal["drafted", "failed"]


class CalendarService:
    def __init__(
        self,
        tool: CalendarTool,
        store: CalendarStore,
        settings: CalendarSettings,
        llm: LLMClient | None = None,
        tz: ZoneInfo | None = None,
    ) -> None:
        self._tool = tool
        self._store = store
        self._llm = llm
        self._tz = tz or ZoneInfo("Asia/Hong_Kong")
        self.settings = settings

    def sync(self) -> SyncResult:
        """Copy upcoming events from iCloud into the DB. Raises CalendarError on
        iCloud problems; the DB is only touched after a complete, successful read."""
        calendars = self.settings.read_calendars or self._tool.list_calendars()
        events = self._tool.upcoming(calendars, self.settings.sync_days)
        self._store.replace_events(events)
        return SyncResult(events=len(events), calendars=len(calendars))

    def process_resolved(self) -> list[WriteOutcome]:
        """Act on every event request the user has decided on. Safe to call any
        time: the DB decides what is due, so a missed Redis message only delays it."""
        outcomes: list[WriteOutcome] = []
        with self._store.write_lock() as locked:
            if not locked:
                return outcomes
            for request_id, approval_id, decision, event in self._store.list_resolved_requests():
                if decision != "approved":
                    self._store.mark_request(request_id, "skipped")
                    outcomes.append(WriteOutcome(request_id, "skipped"))
                    continue
                # Re-read right before the side effect; never act on a stale answer.
                if self._store.approval_status(approval_id) != "approved":
                    continue
                try:
                    self._tool.create(self.settings.write_calendar, event)
                except CalendarError as exc:
                    # Not retried automatically: a human should see why it failed.
                    self._store.mark_request(request_id, "failed", str(exc))
                    outcomes.append(WriteOutcome(request_id, "failed"))
                    continue
                self._store.mark_request(request_id, "written")
                outcomes.append(WriteOutcome(request_id, "written"))
        return outcomes

    def process_intents(self) -> list[IntentOutcome]:
        """Draft an event request (pending approval) for every sentence waiting.
        Nothing here writes to iCloud."""
        outcomes: list[IntentOutcome] = []
        with self._store.write_lock() as locked:
            if not locked:
                return outcomes
            for intent_id, text in self._store.list_pending_intents():
                try:
                    if self._llm is None:
                        raise IntentError(LLM_MISSING)
                    draft = parse_intent(self._llm, text, datetime.now(timezone.utc), self._tz)
                except IntentError as exc:
                    self._store.fail_intent(intent_id, str(exc))
                    outcomes.append(IntentOutcome(intent_id, "failed"))
                    continue
                except LLMError:
                    # Provider details stay in the agent log, not on the dashboard.
                    self._store.fail_intent(intent_id, LLM_UNAVAILABLE)
                    outcomes.append(IntentOutcome(intent_id, "failed"))
                    continue
                self._store.create_request(
                    intent_id,
                    draft,
                    approval_title=f"新增行事曆事件：{draft.title}",
                    approval_detail=describe_draft(draft, text),
                )
                outcomes.append(IntentOutcome(intent_id, "drafted"))
        return outcomes
