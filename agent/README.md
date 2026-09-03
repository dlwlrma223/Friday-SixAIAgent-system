# agent

Python orchestrator. Talks to `api` only via Redis, never direct HTTP.

## Run standalone

```
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
REDIS_URL=redis://localhost:6379 python src/main.py
```

## Lint

```
ruff check .
```
