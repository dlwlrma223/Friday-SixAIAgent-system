# agent

Python orchestrator (LangGraph). Talks to `api` only via Redis, never direct HTTP.

## Layout

| Path | What it does |
|---|---|
| `src/main.py` | Long-running process: startup checks, Redis heartbeat, listens for approval decisions |
| `src/graph.py` | LangGraph graph. One node so far, `research`; later agents route into it |
| `src/research/service.py` | Research entry point for other agents: PII guard → audit log → search |
| `src/research/store.py` | Postgres access for `research_queries`, `approvals`, `personal_terms` |
| `src/tools/research.py` | Tavily wrapper, returns a typed `ResearchResponse` |
| `src/tools/pii_guard.py` | Regex + `personal_terms` check that decides whether a query may leave |
| `src/db.py` | psycopg connection pool (same `DB_*` names as `api`) |
| `src/tools/calendar.py` | Minimal iCloud CalDAV client: list calendars, read upcoming events, write one event. The only module that reads the iCloud credentials |
| `src/tools/llm.py` | One JSON-returning LLM call against any OpenAI-compatible API, with an optional fallback provider |
| `src/tools/llm_anthropic.py` | Claude through the Anthropic SDK (used when the model name starts with `claude-`) |
| `src/calendar_agent/intent.py` | Sentence → validated event draft |
| `src/calendar_agent/service.py` | Sync iCloud → DB, draft requests from sentences, write approved requests to iCloud |
| `src/calendar_agent/store.py` | Postgres access for `calendar_events`, `calendar_event_requests`, `calendar_intents` |

## Approval flow

A query that trips the PII guard is not sent. It is stored as `pending_approval`
with a row in `approvals`. When the user approves or skips it on the dashboard,
`api` updates the row and publishes to Redis channel `friday:approvals`.

`main.py` treats that message only as a nudge: it then asks the DB which parked
queries have been decided, sends the approved ones (`approved_sent`) and closes
the skipped ones (`skipped`). It also sweeps every 60 seconds and on every
(re)subscribe, so a missed message only delays things. A Postgres advisory lock
stops two agent tasks from sending the same query twice.

## Calendar flow

```
sentence typed on the dashboard ──▶ calendar_intents (pending)
        │  Redis nudge on friday:calendar (or the 60s sweep)
        ▼
LLM turns it into a draft ──▶ validated here ──▶ calendar_event_requests + approvals (pending)
        │  user clicks Approve; Redis nudge on friday:approvals
        ▼
approval re-read from the DB ──▶ written to the CALENDAR_WRITE calendar on iCloud ──▶ re-sync
```

Separately, every `CALENDAR_SYNC_MINUTES` the agent copies the next
`CALENDAR_SYNC_DAYS` of events from iCloud into `calendar_events`.

What leaves the system: to iCloud, the event being written; to the LLM, exactly
three lines (local time, timezone, the sentence). Event titles never go to the LLM
and never appear in logs.

## Run standalone

Python 3.12 (same as the Dockerfile).

```
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # runtime deps + pytest + ruff
python -m src.main
```

`requirements.txt` is what the Docker image installs (runtime only);
`requirements-dev.txt` adds test/lint tools for local use.

With Docker Compose (from the repo root):

```
docker compose up -d --force-recreate agent    # --force-recreate re-reads .env
docker compose exec agent python -m src.graph "What is pgvector?"
```

## Environment

| Variable | Local (compose) | Prod (ECS task def) |
|---|---|---|
| `REDIS_URL` | `redis://redis:6379` | `rediss://...:6379` (TLS) |
| `REDIS_AUTH_TOKEN` | unset | Secrets Manager `friday/redis/auth` |
| `DB_HOST` / `DB_PORT` | `db` / `5432` | RDS endpoint |
| `DB_USER` / `DB_PASSWORD` / `DB_NAME` | from `.env` | Secrets Manager `friday/rds/postgres` |
| `DB_SSL` | `disable` | unset → `verify-full` with `certs/rds-global-bundle.pem` |
| `TAVILY_API_KEY` | from `.env` | Secrets Manager `friday/tavily/api-key` |
| `DB_POOL_MAX` | default 5 | default 5 |
| `ICLOUD_USERNAME` / `ICLOUD_APP_PASSWORD` | from `.env` (app-specific password) | not deployed yet |
| `CALENDAR_READ` / `CALENDAR_WRITE` | empty = all / `Friday` | same |
| `CALENDAR_SYNC_DAYS` / `CALENDAR_SYNC_MINUTES` | 30 / 30 | same |
| `CALENDAR_TZ` | default `Asia/Hong_Kong` | same |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | Gemini key / Gemini OpenAI-compatible URL / `gemini-flash-lite-latest` | not deployed yet |
| `LLM_FALLBACK_API_KEY` / `LLM_FALLBACK_MODEL` | empty / `claude-haiku-4-5` | not deployed yet |

Never put secret values in committed files. Without `TAVILY_API_KEY` the
heartbeat still runs; Research is disabled and parked queries stay parked.
Without the iCloud variables the calendar agent is disabled; without an LLM key
sync and approved writes still work, and typed sentences fail with a clear message.
The startup log prints which LLM models are in use (`llm: gemini-flash-lite-latest`).

## Lint / test

```
ruff check src
pytest          # 134 tests, all with fakes (search, store, CalDAV, LLM), no network
```
