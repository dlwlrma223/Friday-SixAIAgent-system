# CLAUDE.md — Personal AI Team Project

This file is the working brief for Claude Code on this repo. Read this fully before writing code. Work phase by phase, in order — do not skip ahead to a later phase's agent before the current phase's acceptance criteria are met.

## 1. What this project is

A personal assistant system made of 6 AI agents, each responsible for one life domain, coordinated through a web dashboard where the user approves any action that has real-world effect (sending an email, applying to a job, confirming a bill payment, etc).

The 6 agents: **Calendar, Home, Research, Study, Finance, Jobs**.

`Research` is not user-facing — it is an internal tool other agents call to search the web.

## 2. Language

Communicate with the user primarily in **Traditional Chinese (繁體中文)** — commit messages, PR descriptions, README files, and any chat/CLI output to the user. Variable names, function names, and other identifiers in code stay in English as normal. English technical terms (API, endpoint, schema, etc.) can stay in English inline within Chinese sentences where that's the natural convention.

**Code comments are the one exception: write them short and in English**, not Traditional Chinese. Only comment the non-obvious "why" (a hidden constraint, a workaround, a subtle invariant) — one line is enough. Detailed rationale, decision history, and "what changed and why" belong in the progress log (see Section 11), not in inline comments — the user reads the log for that, not the source.

## 3. Non-negotiable design rules

- **Human approval before any external side effect.** Any action that sends something, submits something, spends money, or changes a third-party system (job application, autopay confirmation, calendar write, etc.) must be created in a `pending` state and require an explicit approve action from the dashboard before execution. Never auto-execute these.
- **No auto-submission of job applications.** The Jobs agent may draft and match, but the actual submission step always waits for human approval. Do not build a "fully autonomous apply" mode even if asked to optimize for speed later.
- **Secrets never in code or repo.** All API keys, tokens, and credentials go through AWS Secrets Manager in production and `.env` (gitignored) locally. Never hardcode, never log secret values.
- **Least-privilege credentials.** Any exchange/bank/API integration should request read-only scopes unless a write scope is explicitly required for an approved action.
- **Data boundaries.** Finance and Home (camera) data are sensitive. Do not send raw financial data or camera frames to third-party LLM APIs unless the specific agent's design calls for it and the user has been told. Prefer summarizing/extracting structured fields locally before any LLM call where feasible.

## 4. Tech stack (fixed — do not substitute without asking)

| Layer | Technology |
|---|---|
| Frontend | React + Vite + TypeScript |
| API backend | Node.js + TypeScript (Fastify) |
| Agent orchestrator | Python (LangGraph — decided at Phase 2, do not switch) |
| Database | PostgreSQL (RDS in prod) with `pgvector` extension |
| Queue / pub-sub | Redis (ElastiCache in prod) |
| Local dev | Docker Compose |
| Cloud | AWS: ECR, ECS Fargate, RDS, ElastiCache, S3+CloudFront, EventBridge, Secrets Manager |
| CI/CD | GitHub Actions → ECR → ECS |
| Mobile backend (Phase 9 only) | Java Spring Boot |

Two backend services, not one: `api` (Node.js, talks to frontend via HTTP + WebSocket) and `agent` (Python, runs orchestration logic). They communicate via Redis, never by direct HTTP calls to each other.

## 5. Repo structure to create

```
/frontend          — React + Vite dashboard
/api                — Node.js + TypeScript backend
/agent               — Python agent orchestrator
/infra               — IaC (Dockerfiles, docker-compose.yml, AWS deploy configs)
docker-compose.yml
CLAUDE.md            — this file
```

## 6. Database schema (starting point — extend as needed per agent, do not remove existing columns without migration)

```sql
CREATE TABLE agents (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,             -- calendar / home / research / study / finance / jobs
  status TEXT DEFAULT 'idle'
);

CREATE TABLE tasks (
  id SERIAL PRIMARY KEY,
  agent_id INT REFERENCES agents(id),
  title TEXT NOT NULL,
  status TEXT DEFAULT 'queued',   -- queued / in_progress / done / waiting_on_you
  created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE approvals (
  id SERIAL PRIMARY KEY,
  agent_id INT REFERENCES agents(id),
  title TEXT NOT NULL,
  detail TEXT,
  status TEXT DEFAULT 'pending',  -- pending / approved / skipped
  created_at TIMESTAMP DEFAULT now(),
  resolved_at TIMESTAMP
);

CREATE TABLE job_applications (
  id SERIAL PRIMARY KEY,
  company TEXT,
  position TEXT,
  jd_text TEXT,
  match_score NUMERIC,
  status TEXT DEFAULT 'draft',    -- draft / pending_approval / submitted / rejected
  applied_at TIMESTAMP
);

CREATE TABLE subjects (             -- Study agent
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL                -- English / Japanese / taxi license / electrician / AWS SAA
);

CREATE TABLE study_sessions (
  id SERIAL PRIMARY KEY,
  subject_id INT REFERENCES subjects(id),
  duration_minutes INT,
  self_rating INT,                  -- 1-5 mastery self-assessment
  notes TEXT,
  created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE personal_terms (        -- Research PII guard: terms that must never leave in a query
  id SERIAL PRIMARY KEY,
  term TEXT NOT NULL UNIQUE,
  category TEXT NOT NULL DEFAULT 'other',  -- name / address / employer / account / other
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE research_queries (      -- audit log of every Research call, sent or not
  id SERIAL PRIMARY KEY,
  agent_id INT REFERENCES agents(id),
  query TEXT NOT NULL,
  purpose TEXT,
  pii_flags TEXT[] NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'sent',     -- sent / pending_approval / approved_sent / skipped / failed
  approval_id INT REFERENCES approvals(id),
  result_count INT,
  answer_preview TEXT,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE TABLE calendar_events (       -- local mirror of upcoming iCloud events, refreshed by the agent
  id SERIAL PRIMARY KEY,
  uid TEXT NOT NULL,
  calendar_name TEXT NOT NULL,
  title TEXT NOT NULL,
  starts_at TIMESTAMPTZ NOT NULL,
  ends_at TIMESTAMPTZ,
  all_day BOOLEAN NOT NULL DEFAULT false,
  location TEXT,
  synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (calendar_name, uid, starts_at)
);

CREATE TABLE calendar_event_requests ( -- a calendar write waiting for approval
  id SERIAL PRIMARY KEY,
  requested_by INT REFERENCES agents(id),  -- which agent asked; NULL = the user directly
  event_uid TEXT NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
  title TEXT NOT NULL,
  starts_at TIMESTAMPTZ NOT NULL,
  ends_at TIMESTAMPTZ NOT NULL,
  all_day BOOLEAN NOT NULL DEFAULT false,
  location TEXT,
  notes TEXT,
  reason TEXT,
  status TEXT NOT NULL DEFAULT 'pending_approval',  -- pending_approval / written / skipped / failed
  approval_id INT REFERENCES approvals(id),
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE TABLE calendar_intents (      -- a sentence typed on the dashboard for the calendar agent
  id SERIAL PRIMARY KEY,
  text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',  -- pending / drafted / failed
  request_id INT REFERENCES calendar_event_requests(id),
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE TABLE study_goals (           -- something to learn, and the plan the study agent wrote for it
  id SERIAL PRIMARY KEY,
  subject_id INT REFERENCES subjects(id),
  request_text TEXT NOT NULL,
  title TEXT,
  status TEXT NOT NULL DEFAULT 'pending',  -- pending / planned / failed
  overview TEXT,
  facts JSONB NOT NULL DEFAULT '[]',       -- [{label, value}]
  total_weeks INT,
  sources JSONB NOT NULL DEFAULT '[]',     -- [{id, title, url}]
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE TABLE study_modules (         -- one chapter of a study plan
  id SERIAL PRIMARY KEY,
  goal_id INT NOT NULL REFERENCES study_goals(id) ON DELETE CASCADE,
  position INT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT,
  topics TEXT[] NOT NULL DEFAULT '{}',
  est_hours NUMERIC,
  week INT,
  source_ids INT[] NOT NULL DEFAULT '{}',
  materials_status TEXT NOT NULL DEFAULT 'none',  -- none / pending / ready / failed (added in 0019)
  materials_error TEXT,
  materials_sources JSONB NOT NULL DEFAULT '[]',
  UNIQUE (goal_id, position)
);

CREATE TABLE study_cards (           -- flash cards for one module
  id SERIAL PRIMARY KEY,
  module_id INT NOT NULL REFERENCES study_modules(id) ON DELETE CASCADE,
  position INT NOT NULL,
  front TEXT NOT NULL,
  back TEXT NOT NULL,
  UNIQUE (module_id, position)
);

CREATE TABLE study_questions (       -- multiple-choice questions for one module, always 4 options
  id SERIAL PRIMARY KEY,
  module_id INT NOT NULL REFERENCES study_modules(id) ON DELETE CASCADE,
  position INT NOT NULL,
  question TEXT NOT NULL,
  options JSONB NOT NULL,
  correct_index INT NOT NULL,              -- 0-3
  explanation TEXT,
  UNIQUE (module_id, position)
);

CREATE TABLE study_attempts (        -- every answer given; drives spaced repetition later
  id SERIAL PRIMARY KEY,
  question_id INT NOT NULL REFERENCES study_questions(id) ON DELETE CASCADE,
  chosen_index INT NOT NULL,
  is_correct BOOLEAN NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE llm_usage (             -- one row per LLM call, for cost tracking and caps
  id SERIAL PRIMARY KEY,
  purpose TEXT NOT NULL,                   -- study_plan / study_material / ...
  model TEXT NOT NULL,
  input_tokens INT NOT NULL DEFAULT 0,
  output_tokens INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- pgvector tables added per-agent as needed (study notes, CV/JD embeddings)
```

## 7. Phase checklist

Work through phases in order. Each phase has a "definition of done" — do not mark a phase complete or move on until it's met. Stop and ask the user (do not guess) whenever a phase requires a credential, an external account signup, or a decision explicitly marked **[ASK USER]** below.

### Phase 0 — Local Docker environment ✅ done
- [x] `docker-compose.yml` bringing up `frontend`, `api`, `agent`, `db` (`pgvector/pgvector:pg16` — plain postgres:16 has no pgvector), `redis` (redis:7)
- [x] `api` exposes a health check endpoint
- [x] `agent` connects to Redis and logs a heartbeat
- [x] `frontend` can hit `api` health check and render status
- **Done when:** `docker compose up` brings up all 5 services with no errors, frontend shows "connected".

### Phase 1 — AWS foundation ✅ done
- [x] **[ASK USER]** confirm AWS account/region before creating any resource — ap-southeast-1
- [x] ECR repos for `api` and `agent` images
- [x] ECS Fargate cluster with two services
- [x] RDS Postgres instance, `pgvector` extension enabled
- [x] ElastiCache Redis
- [x] Secrets Manager entries for DB credentials at minimum
- [x] VPC/security groups: RDS and Redis reachable only from within the ECS cluster's VPC, not public
- **Done when:** `api` service deployed on ECS can read/write RDS through the deployed environment, verified via a smoke-test endpoint. — verified via `/db-check`.

Bonus (beyond this phase's checklist): `frontend` deployed to S3 + CloudFront (see `infra/aws-resources.md`). `api` still only reachable via its ECS task's public IP (no ALB yet — deferred, costs ~$16-17/mo after the 12-month free tier).

### Phase 2 — Research agent (internal tool) ✅ done
- [x] **[ASK USER]** which search API to use — Tavily (decided 2026-09-16); key lives in `.env` locally as `TAVILY_API_KEY`, Secrets Manager in prod (`friday/tavily/api-key`)
- [x] Implement as a callable tool inside the `agent` orchestrator, not a standalone user-facing agent — `agent/src/graph.py` (LangGraph node) → `agent/src/research/service.py` → `agent/src/tools/research.py`; PII guard (`agent/src/tools/pii_guard.py` + `personal_terms` table) parks suspicious queries as a pending approval instead of sending them
- **Done when:** another agent (test with a stub) can call Research and get back structured results. — verified 2026-09-23 with stubbed search/store tests, a real Tavily call locally, and the ECS agent task (task def rev 4) reaching RDS + Tavily key in prod.

Follow-up done 2026-10-04 (dashboard approval for parked research queries, verified locally end to end):
- `api`: `GET /approvals`, `GET /research/queries`, `POST /approvals/:id/approve|skip` (`api/src/dashboard.ts`), all behind `Authorization: Bearer <DASHBOARD_TOKEN>` (`api/src/auth.ts`, fails closed with 503 when the token is unset). After the DB update the api publishes to Redis channel `friday:approvals` (`api/src/pubsub.ts`).
- `agent`: `src/main.py` subscribes to that channel. The message is only a nudge — the agent asks the DB which parked queries were decided (`ResearchService.process_resolved()`), also every 60s and on reconnect, under a Postgres advisory lock.
- `frontend`: "Needs Your Approval" and "Run Log" panels read the api (`frontend/src/api.ts`); every other panel is still seed data. DB text is rendered with `textContent`, never `innerHTML`.

Still open: these routes are not enabled in prod (no `DASHBOARD_TOKEN` secret; the CloudFront frontend is HTTPS and the api is HTTP-only, so the browser blocks it — needs HTTPS in front of the api). No agent calls `ResearchService.request()` from `main.py` yet; that waits for the first calling agent.

Handoff docs: `PROJECT_STATE.md` (where things stand) and `HANDOFF.md` (how to pick the work up) live outside this repo in `~/Documents/sidePorject/` (the user keeps them there; not in git) — read both at the start of a new session and update them after each phase.

### Phase 3 — Calendar agent ✅ done locally (prod not deployed yet)
- [x] **[ASK USER]** for iCloud app-specific password before implementing — done 2026-10-04; `ICLOUD_USERNAME` / `ICLOUD_APP_PASSWORD` in `.env`, agent only. The user chose their main Apple ID (not a secondary one).
- [x] CalDAV client reads events, writes new events — lives in **`agent`** (`agent/src/tools/calendar.py`), never in `api`: the api is public-facing and must not hold the iCloud password. Hand-written minimal client on `httpx` (the `caldav` package timed out against iCloud). Credentials are only ever sent to `*.icloud.com` over HTTPS, redirects are not followed, errors and logs are scrubbed.
- [x] ~~Dashboard shows upcoming events~~ — **dropped by the user (2026-10-04)**: they want AI-driven scheduling, not a calendar view or a manual form. The dashboard instead has one input box: a sentence goes to `POST /calendar/intents`, the agent asks an LLM to turn it into an event draft, and the draft becomes a pending approval. Events are still synced into `calendar_events` every 30 min (next 30 days) so other agents can read the schedule; `GET /calendar/events` exists but nothing on the dashboard uses it.
- **Done when:** creating an event via the dashboard shows up in the actual iCloud calendar within a minute. — verified locally 2026-10-04: sentence → draft in ~1.5s → Approve → written to iCloud ~1s later, seen on the user's phone.

How it fits together:
- Read: `agent/src/calendar_agent/service.py` `sync()` → `calendar_events`. `CALENDAR_READ` empty = all calendars; `CALENDAR_SYNC_DAYS=30`, `CALENDAR_SYNC_MINUTES=30`.
- Write: only for a `calendar_event_requests` row whose approval is `approved` (re-checked in the DB right before the write), and only into the one calendar named by `CALENDAR_WRITE` (`Friday`). `event_uid` is fixed at request time so a retry overwrites instead of duplicating. Any agent may file a request (`requested_by`, `reason`) — that is the path for cross-agent scheduling (e.g. Home asking Calendar to add a rent reminder).
- LLM (`agent/src/tools/llm.py`, `llm_anthropic.py`, `agent/src/calendar_agent/intent.py`): primary Gemini free tier via its OpenAI-compatible API (`gemini-flash-lite-latest`), optional fallback Claude Haiku 4.5 via the Anthropic SDK (key not set yet). Configured by `LLM_*` / `LLM_FALLBACK_*` in `.env`; a model named `claude-*` uses the Anthropic SDK. Only three lines leave the system per call: local time, timezone, the sentence. The model's answer is validated in code (no past dates, no invented dates, end after start) before anything is filed.
- Provider decisions (user, 2026-10-04): no DeepSeek (data would go to China); Groq is blocked from the user's network (HTTP 403); Gemini free-tier data may be used by Google for training — accepted for calendar sentences only. Revisit before sending Finance/Home data to any LLM.

Still open: not deployed to prod (needs migrations 0010–0012 on RDS, Secrets Manager entries for iCloud + LLM keys, a new agent task definition). The security review of the Phase 3 diff promised before any prod deploy has not been run yet.

### Phase 4 — Study agent (redefined by the user 2026-10-04; in progress)

The user does not want a study logger. They want to state a goal ("我想考 CCNA") and have the agent research it and produce the plan and the materials. Original items (subjects, sessions, pgvector notes, spaced repetition) are folded into the stages below, not dropped.

- [x] **4a — goal → research → study plan.** `POST /study/goals` records the sentence; the agent (`agent/src/study/`, a LangGraph: `draft_queries` → `research` → `write_plan`) asks the LLM for search queries, runs them through `ResearchService` (so they are logged and pass the PII guard), and writes a plan from the numbered sources: overview, exam facts, modules with topics / hours / week / cited sources. Stored in `study_goals` + `study_modules`; new subjects are added to `subjects`. Built and verified locally 2026-10-04 with Gemini (CCNA: 3 searches, 14 sources, 6 modules, ~14s). **Waiting for the user to try it and judge the plan.**
- [x] **4b — study cards and multiple-choice questions** per module. A "Generate cards & quiz" button on each module calls `POST /study/modules/:id/materials`; the agent (`agent/src/study/materials.py`, `build_materials_graph`) searches for the module through Research (queries built in code from the plan, not by the model) and has the `STUDY_MATERIAL` model write 8–12 cards and 8–10 four-option questions. Questions in English, explanations in Traditional Chinese with English terms. Malformed items are dropped and options are shuffled in code so the answer position carries no hint. The dashboard shows flip cards and a one-question-at-a-time quiz; answers are checked server-side (`POST /study/questions/:id/answer`, the correct answer is never sent with the question) and every attempt is stored in `study_attempts` for 4d. Built and verified locally 2026-10-04 with Gemini (~15s per module). **Waiting for the user to try it and judge the quality.**
- [ ] **4c — PDF notes** per module. Files stored locally for now (S3 when this goes to prod).
- [ ] **4d — spaced repetition** from quiz results ("review this today"). Decide after 4b. This carries the original "Done when".
- ~~4e — podcast audio~~ — the user decided not to build this.
- **Done when (4a–4c):** stating a goal yields a researched plan, and each module can produce cards, a quiz and a PDF the user finds usable.

Models (user decision 2026-10-04): start on the free Gemini tier, upgrade later to **Claude Opus 5.5 for planning and Claude Sonnet 5.5 for materials**. Each job has its own `<ROLE>_API_KEY` / `_BASE_URL` / `_MODEL` in `.env` (`STUDY_PLAN_*`, `STUDY_MATERIAL_*`); empty values fall back to `LLM_*`. Switching is a `.env` edit plus recreating the agent, no code change. A Claude subscription (Max/Pro) does not cover API usage; the Anthropic API key is separate and prepaid. The Claude path (`agent/src/tools/llm_anthropic.py`, structured outputs, `fallbacks: "default"`) has only been tested with fakes — verify it against the real API when the key arrives.

Cost control: every model call is recorded in `llm_usage`; `STUDY_DAILY_CALLS` (default 40 per 24h) stops the study agent before a call when exceeded.

Data leaving the system: the goal sentence and the search snippets go to the LLM; search queries go to Tavily. Generated material must cite its sources; it is AI-written and not guaranteed correct.

Later (user's stated direction, not this phase): one shared input box with a router agent that sends each sentence to the right agent. Calendar and Study already use the same "record the sentence → Redis nudge → agent processes" shape so they can be merged.

### Phase 5 — Home agent
- [ ] **[ASK USER]** whether Home Assistant is already running, or needs to be set up (this is manual setup outside code — flag it, don't attempt to automate device pairing)
- [ ] `agent` polls or subscribes to Home Assistant's API for motion events from the Xiaomi camera entity
- [ ] Anomaly logic (e.g., no motion detected for N hours) creates an approval/notification, not a silent auto-action
- **Done when:** a real motion event from Home Assistant appears in the dashboard's run log within seconds.

### Phase 6 — Finance agent
- [ ] **[ASK USER]** for Plaid API keys (sandbox first, then production after Plaid's own review) — do not proceed with real bank credentials until sandbox flow works end to end
- [ ] Read-only transaction and balance sync
- [ ] Spending summary / anomaly detection (duplicate subscriptions etc.)
- [ ] All output framed as informational summary, never as directive financial advice in copy/UI text
- **Done when:** sandbox account data flows through to a dashboard summary correctly.

### Phase 7 — Jobs agent
- [ ] **[ASK USER]** for the user's CV and explicit criteria (role, salary range, location, must-haves) before building matching logic
- [ ] Job board API integration (Adzuna/Jooble or similar with a public API — do not scrape LinkedIn or any site whose ToS prohibits automation)
- [ ] CV/JD embedding + similarity scoring via pgvector
- [ ] Draft generation (tailored CV bullet points / cover letter) for high-match roles
- [ ] Submission is **always** a pending approval — build the approve action to trigger submission, never on a timer or auto-trigger
- **Done when:** a new matching JD produces a draft application sitting in the approvals queue, and clicking approve is what triggers the actual submission.

### Phase 8 — Polish & security pass
- [ ] Every approval-consuming action re-verified to require the approval record's status to be `approved` before executing (no client-side-only checks)
- [ ] WebSocket reconnect handling on the frontend
- [ ] Secrets audit: grep repo history and current code for any accidentally committed keys
- [ ] IAM roles reviewed for least privilege

### Phase 9 — Mobile (separate track, after Phase 8)
- [ ] **[ASK USER]** to confirm mobile UI approach (PWA vs React Native vs native) before starting
- [ ] Spring Boot service exposing a mobile-scoped subset of the API
- [ ] Deployed as its own ECS service, same RDS

## 8. Coding conventions

- TypeScript strict mode on in `api` and `frontend`.
- Python: type hints throughout, `ruff` for linting.
- Every endpoint that mutates data validates its input and returns a typed error on failure — no silent failures.
- Commit messages reference the phase (e.g. `phase2: add CalDAV write endpoint`).
- Write a short README per top-level folder (`api/README.md` etc.) explaining how to run and test that piece in isolation.
- `api/test/` (and any other test folders) are gitignored — tests run locally only, not committed.

## 9. When in doubt

If a task requires a decision this file doesn't cover, or touches money, credentials, or an external account signup, stop and ask the user rather than guessing. It's fine to scaffold and stub in the meantime.

## 10. Engineering review roles for Claude Code

3 specialized subagents live in `.claude/agents/` for review/dev work on this repo — separate from the 6 product agents in section 1 (Calendar/Home/Research/Study/Finance/Jobs), which are the product being built, not roles Claude Code plays:

- `.claude/agents/network-security-agent.md` — 🛡️ Network Security Agent (網絡安全專家): OWASP/secrets/auth/secure-protocol review.
- `.claude/agents/qa-tester-agent.md` — 🧪 QA Tester Agent (自動化測試專家): unit/integration tests, edge cases.
- `.claude/agents/clean-code-agent.md` — 🧹 Clean Code & Refactoring Agent (代碼優化與重構專家): DRY, dead-code removal, style.

**Interaction workflow**: When the user asks for a review, ask which agent they want deployed, or pick the most appropriate one automatically based on the request, and invoke it via the Agent tool with the matching `subagent_type`. Each agent's own file defines its response prefix (e.g. `[🛡️ Network Security Agent]`).

## 11. Progress log

Keep a running project log at `.claude/progress-log.pdf` (source: `.claude/progress-log.html`, gitignored, local-only — not the same thing as this CLAUDE.md working brief). Update it whenever meaningful work happens: what was done, which files were touched and why, and any difficulty hit along the way and how it was resolved. Write it in Traditional Chinese, organized by phase/session.

**Voice: write it as the user, in first person** ("我建了...", "我改成...", "我遇到...然後我...") — as if the user is journaling their own work, not as Claude Code reporting to a client. Never write it as an assistant addressing or describing "the user" in third person, and never phrase entries as the user commanding/instructing Claude. This is the user's own record of what they built. Regenerate the PDF from the HTML source whenever asked to update the log, or proactively after a substantial chunk of work (e.g. finishing a phase, a significant debugging session, a security-fix pass) — convert with headless Chrome: `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu --print-to-pdf="progress-log.pdf" --no-pdf-header-footer "file://<path>/progress-log.html"` (textutil/cupsfilter/pandoc are not reliable for HTML→PDF on this machine).
