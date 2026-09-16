# agent

Python orchestrator. Talks to `api` only via Redis, never direct HTTP.

## Run standalone

```
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
REDIS_URL=redis://localhost:6379 python src/main.py
```

Against ElastiCache (TLS + AUTH) set `REDIS_URL=rediss://...:6379` and `REDIS_AUTH_TOKEN` (injected from Secrets Manager `friday/redis/auth` in ECS — never put the value in `.env` committed files).

## Lint

```
ruff check .
```
