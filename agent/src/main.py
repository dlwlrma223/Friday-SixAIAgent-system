import logging
import os
import time

import redis

from src.calendar_agent.service import CalendarService, load_settings
from src.calendar_agent.store import PostgresCalendarStore
from src.db import build_pool
from src.research.service import ResearchService
from src.research.store import PostgresResearchStore
from src.tools.calendar import CalendarError, build_calendar_tool
from src.tools.research import ResearchError, build_research_tool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("agent")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
# Set in prod (ElastiCache AUTH). Local compose redis has no password.
REDIS_AUTH_TOKEN = os.environ.get("REDIS_AUTH_TOKEN")
HEARTBEAT_INTERVAL_SECONDS = 5
# api publishes here after an approve/skip. Only a nudge: the DB is the truth.
APPROVALS_CHANNEL = "friday:approvals"
# Fallback sweep, in case a message was published while we were not listening.
SWEEP_INTERVAL_SECONDS = 60


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
        store = PostgresCalendarStore(build_pool(max_size=2))
        return CalendarService(build_calendar_tool(), store, load_settings())
    except CalendarError as exc:
        logger.error("calendar disabled: %s", exc)
        return None


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
    next_calendar_sync = 0.0
    client = redis.Redis.from_url(REDIS_URL, password=REDIS_AUTH_TOKEN)
    pubsub = None
    next_sweep = 0.0

    while True:
        nudged = False
        try:
            if pubsub is None:
                pubsub = client.pubsub(ignore_subscribe_messages=True)
                pubsub.subscribe(APPROVALS_CHANNEL)
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

        if service and (nudged or time.monotonic() >= next_sweep):
            process_approvals(service)
            next_sweep = time.monotonic() + SWEEP_INTERVAL_SECONDS

        if calendar and time.monotonic() >= next_calendar_sync:
            sync_calendar(calendar)
            next_calendar_sync = time.monotonic() + calendar.settings.sync_minutes * 60


if __name__ == "__main__":
    main()
