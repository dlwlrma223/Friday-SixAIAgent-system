import logging
import os
import time

import redis

from src.calendar_agent.service import CalendarService, load_settings
from src.calendar_agent.store import PostgresCalendarStore
from src.db import build_pool
from src.research.service import ResearchService
from src.research.store import PostgresResearchStore
from src.study.graph import build_materials_graph, build_study_graph
from src.study.service import DEFAULT_DAILY_CALLS, StudyService
from src.study.store import PostgresStudyStore
from src.tools.calendar import CalendarError, build_calendar_tool, calendar_timezone
from src.tools.llm import (
    DEFAULT_FALLBACK_MODEL,
    DEFAULT_MODEL,
    LLMError,
    build_llm_client,
    build_llm_for,
    resolve_role,
)
from src.tools.research import ResearchError, build_research_tool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("agent")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
# Set in prod (ElastiCache AUTH). Local compose redis has no password.
REDIS_AUTH_TOKEN = os.environ.get("REDIS_AUTH_TOKEN")
HEARTBEAT_INTERVAL_SECONDS = 5
# api publishes here after an approve/skip. Only a nudge: the DB is the truth.
APPROVALS_CHANNEL = "friday:approvals"
# api publishes here when I type a sentence for the calendar agent.
CALENDAR_CHANNEL = "friday:calendar"
# api publishes here when I give the study agent a new goal.
STUDY_CHANNEL = "friday:study"
# Each job the study agent does can run on its own model (see resolve_role).
STUDY_ROLES = ("STUDY_PLAN", "STUDY_MATERIAL")
# Fallback sweep, in case a message was published while we were not listening.
SWEEP_INTERVAL_SECONDS = 60
# (key variable, model variable) for the primary and the fallback provider.
LLM_SLOTS = (("LLM_API_KEY", "LLM_MODEL"), ("LLM_FALLBACK_API_KEY", "LLM_FALLBACK_MODEL"))


def startup_checks() -> None:
    """Log whether Postgres and the Tavily key are usable. Never raises, never logs values."""
    try:
        with build_pool(max_size=1) as pool, pool.connection(timeout=10) as conn:
            row = conn.execute("SELECT count(*) FROM agents").fetchone()
        logger.info("db ok (agents=%s)", row[0] if row else "?")
    except Exception as exc:  # keep the heartbeat alive whatever failed
        logger.error("db check failed: %s", exc)
    logger.info("tavily: %s", "configured" if os.environ.get("TAVILY_API_KEY") else "missing")
    icloud = os.environ.get("ICLOUD_USERNAME") and os.environ.get("ICLOUD_APP_PASSWORD")
    logger.info("icloud: %s", "configured" if icloud else "missing")
    # Model names are not secret; logging them shows which AI is in use.
    models = [
        os.environ.get(model) or default
        for (key, model), default in zip(LLM_SLOTS, (DEFAULT_MODEL, DEFAULT_FALLBACK_MODEL))
        if os.environ.get(key)
    ]
    logger.info("llm: %s", " -> ".join(models) if models else "missing")
    for role in STUDY_ROLES:
        key, _, model = resolve_role(role)
        logger.info("%s: %s%s", role.lower(), model, "" if key else " (no key)")


def build_research_service() -> ResearchService | None:
    """None when Research can't run (no Tavily key); the heartbeat still works."""
    try:
        return ResearchService(build_research_tool(), PostgresResearchStore(build_pool()))
    except ResearchError as exc:
        logger.error("research disabled: %s", exc)
        return None


def build_calendar_service() -> CalendarService | None:
    """None when iCloud isn't configured; everything else keeps running."""
    try:
        # Before the pool: without credentials there is nothing to connect for.
        tool = build_calendar_tool()
    except CalendarError as exc:
        logger.error("calendar disabled: %s", exc)
        return None
    try:
        llm = build_llm_client()
    except LLMError as exc:
        # Sync and approved writes still work; typed sentences get a clear failure.
        logger.error("calendar drafting disabled: %s", exc)
        llm = None
    store = PostgresCalendarStore(build_pool(max_size=2))
    return CalendarService(tool, store, load_settings(), llm=llm, tz=calendar_timezone())


def build_study_service(research: ResearchService | None) -> StudyService | None:
    """None when the study agent can't run; everything else keeps running."""
    if research is None:
        logger.error("study disabled: it needs Research (TAVILY_API_KEY)")
        return None
    store = PostgresStudyStore(build_pool(max_size=2))
    try:
        llm = build_llm_for(
            "STUDY_PLAN", usage_sink=lambda *usage: store.record_usage("study_plan", *usage)
        )
    except LLMError as exc:
        logger.error("study disabled: %s", exc)
        return None
    try:
        material_llm = build_llm_for(
            "STUDY_MATERIAL",
            usage_sink=lambda *usage: store.record_usage("study_material", *usage),
        )
        language = os.environ.get("STUDY_MATERIAL_LANGUAGE") or "zh-TW"
        logger.info("study_material language: %s", language)
        materials_graph = build_materials_graph(material_llm, research, language)
    except LLMError as exc:
        # Planning still works; module material requests will simply wait.
        logger.error("study materials disabled: %s", exc)
        materials_graph = None
    try:
        daily = int(os.environ.get("STUDY_DAILY_CALLS") or DEFAULT_DAILY_CALLS)
    except ValueError:
        daily = DEFAULT_DAILY_CALLS
    return StudyService(
        build_study_graph(llm, research), store, daily_calls=daily, materials_graph=materials_graph
    )


def process_study_goals(service: StudyService) -> None:
    """Plan goals that are waiting. Never raises."""
    try:
        for outcome in service.process_goals():
            # Ids and counts only: goal text is personal and stays out of the logs.
            logger.info(
                "study goal %s -> %s (modules=%s)", outcome.goal_id, outcome.status, outcome.modules
            )
        for done in service.process_materials():
            logger.info(
                "study module %s materials -> %s (cards=%s, questions=%s)",
                done.module_id, done.status, done.cards, done.questions,
            )
    except Exception as exc:
        logger.error("study sweep failed: %s", exc.__class__.__name__)


def sync_calendar(service: CalendarService) -> None:
    """Refresh the local copy of upcoming events. Never raises."""
    try:
        result = service.sync()
        # Counts only: event titles are personal and stay out of the logs.
        logger.info("calendar sync ok (events=%s, calendars=%s)", result.events, result.calendars)
    except CalendarError as exc:  # message is already scrubbed of credentials
        logger.error("calendar sync failed: %s", exc)
    except Exception as exc:  # DB problem etc; class name only, to be safe
        logger.error("calendar sync failed: %s", exc.__class__.__name__)


def process_calendar_requests(service: CalendarService) -> bool:
    """Draft requests from typed sentences, write approved events to iCloud,
    close skipped ones. Never raises. Returns True if something was written,
    so the caller can re-sync."""
    try:
        for drafted in service.process_intents():
            logger.info("calendar intent %s -> %s", drafted.intent_id, drafted.status)
        outcomes = service.process_resolved()
    except Exception as exc:
        logger.error("calendar request sweep failed: %s", exc.__class__.__name__)
        return False
    for outcome in outcomes:
        logger.info("calendar request %s -> %s", outcome.request_id, outcome.status)
    return any(o.status == "written" for o in outcomes)


def process_approvals(service: ResearchService) -> None:
    """Send or drop parked research queries the user has decided on. Never raises."""
    try:
        for outcome in service.process_resolved():
            # Ids and counts only: the query text itself may contain personal data.
            results = len(outcome.response.results) if outcome.response else 0
            logger.info(
                "research log %s -> %s (results=%s)", outcome.log_id, outcome.status, results
            )
    except Exception as exc:  # a DB/Tavily problem must not kill the loop
        logger.error("approval sweep failed: %s", exc)


def main() -> None:
    startup_checks()
    service = build_research_service()
    calendar = build_calendar_service()
    study = build_study_service(service)
    next_calendar_sync = 0.0
    client = redis.Redis.from_url(REDIS_URL, password=REDIS_AUTH_TOKEN)
    pubsub = None
    next_sweep = 0.0

    while True:
        nudged = False
        try:
            if pubsub is None:
                pubsub = client.pubsub(ignore_subscribe_messages=True)
                pubsub.subscribe(APPROVALS_CHANNEL, CALENDAR_CHANNEL, STUDY_CHANNEL)
                # Anything published before this point was missed; sweep now.
                next_sweep = 0.0
            # Doubles as the sleep between heartbeats; returns early on a message.
            nudged = pubsub.get_message(timeout=HEARTBEAT_INTERVAL_SECONDS) is not None
            client.ping()
            logger.info("heartbeat ok (redis=%s)", REDIS_URL)
        except redis.RedisError as exc:
            logger.error("heartbeat failed: %s", exc)
            pubsub = None
            time.sleep(HEARTBEAT_INTERVAL_SECONDS)

        if nudged or time.monotonic() >= next_sweep:
            if service:
                process_approvals(service)
            if calendar and process_calendar_requests(calendar):
                # Show the new event on the dashboard right away.
                next_calendar_sync = 0.0
            if study:
                process_study_goals(study)
            next_sweep = time.monotonic() + SWEEP_INTERVAL_SECONDS

        if calendar and time.monotonic() >= next_calendar_sync:
            sync_calendar(calendar)
            next_calendar_sync = time.monotonic() + calendar.settings.sync_minutes * 60


if __name__ == "__main__":
    main()
