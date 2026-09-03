import logging
import os
import time

import redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("agent")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
HEARTBEAT_INTERVAL_SECONDS = 5


def main() -> None:
    client = redis.Redis.from_url(REDIS_URL)

    while True:
        try:
            client.ping()
            logger.info("heartbeat ok (redis=%s)", REDIS_URL)
        except redis.RedisError as exc:
            logger.error("heartbeat failed: %s", exc)
        time.sleep(HEARTBEAT_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
