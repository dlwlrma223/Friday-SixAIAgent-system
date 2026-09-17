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

-- pgvector tables added per-agent as needed (study notes, CV/JD embeddings)
```

## 7. Phase checklist

Work through phases in order. Each phase has a "definition of done" — do not mark a phase complete or move on until it's met. Stop and ask the user (do not guess) whenever a phase requires a credential, an external account signup, or a decision explicitly marked **[ASK USER]** below.

### Phase 0 — Local Docker environment
- [ ] `docker-compose.yml` bringing up `frontend`, `api`, `agent`, `db` (postgres:16), `redis` (redis:7)
- [ ] `api` exposes a health check endpoint
- [ ] `agent` connects to Redis and logs a heartbeat
- [ ] `frontend` can hit `api` health check and render status
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

### Phase 2 — Research agent (internal tool)
- [x] **[ASK USER]** which search API to use — Tavily (decided 2026-09-16); key lives in `.env` locally as `TAVILY_API_KEY`, Secrets Manager in prod
- [ ] Implement as a callable tool inside the `agent` orchestrator, not a standalone user-facing agent
- **Done when:** another agent (test with a stub) can call Research and get back structured results.

### Phase 3 — Calendar agent
- [ ] **[ASK USER]** for iCloud app-specific password before implementing — do not attempt with the primary Apple ID password
- [ ] CalDAV client in `api` (or `agent`, pick one and be consistent) reads events, writes new events
- [ ] Dashboard shows upcoming events
- **Done when:** creating an event via the dashboard shows up in the actual iCloud calendar within a minute.

### Phase 4 — Study agent
- [ ] `subjects` seeded with the 5 subjects the user gave: English, Japanese, taxi license (的士牌), electrician (電工), AWS SAA
- [ ] `study_sessions` logging endpoint
- [ ] pgvector table for notes per subject, semantic search endpoint
- [ ] Spaced-repetition scheduling logic (SM-2 or similar) surfaces "review this today" prompts on the dashboard
- **Done when:** logging a study session updates progress, and the dashboard surfaces a due-for-review item correctly after the algorithm's interval.

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
