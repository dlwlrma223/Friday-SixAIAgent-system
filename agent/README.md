# agent

Python orchestrator. Talks to `api` only via Redis, never direct HTTP.

## Run standalone

Python 3.12 (same as the Dockerfile).

```
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # runtime deps + pytest + ruff
REDIS_URL=redis://localhost:6379 python src/main.py
```

`requirements.txt` is what the Docker image installs (runtime only);
`requirements-dev.txt` adds test/lint tools for local use.

Against ElastiCache (TLS + AUTH) set `REDIS_URL=rediss://...:6379` and `REDIS_AUTH_TOKEN` (injected from Secrets Manager `friday/redis/auth` in ECS — never put the value in `.env` committed files).

## Lint / test

```
ruff check .
pytest
```
