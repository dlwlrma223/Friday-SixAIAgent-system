import logging
import os
import time

import redis

from src.db import build_pool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("agent")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
# Set in prod (ElastiCache AUTH). Local compose redis has no password.
REDIS_AUTH_TOKEN = os.environ.get("REDIS_AUTH_TOKEN")
HEARTBEAT_INTERVAL_SECONDS = 5


def startup_checks() -> None:
    """Log whether Postgres and the Tavily key are usable. Never raises, never logs values."""
    try:
        with build_pool(max_size=1) as pool, pool.connection(timeout=10) as conn:
            row = conn.execute("SELECT count(*) FROM agents").fetchone()
        logger.info("db ok (agents=%s)", row[0] if row else "?")
    except Exception as exc:  # keep the heartbeat alive whatever failed
        logger.error("db check failed: %s", exc)

    logger.info("tavily: %s", "configured" if os.environ.get("TAVILY_API_KEY") else "missing")


def main() -> None:
    startup_checks()
    client = redis.Redis.from_url(REDIS_URL, password=REDIS_AUTH_TOKEN)

    while True:
        try:
            client.ping()
            logger.info("heartbeat ok (redis=%s)", REDIS_URL)
        except redis.RedisError as exc:
            logger.error("heartbeat failed: %s", exc)
        time.sleep(HEARTBEAT_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
