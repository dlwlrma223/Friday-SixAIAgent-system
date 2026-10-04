import {
  ApiError,
  answerStudyQuestion,
  fetchStudyMaterials,
  requestStudyMaterials,
  fetchCalendarIntents,
  fetchPendingApprovals,
  fetchResearchQueries,
  fetchStudyGoal,
  fetchStudyGoals,
  getToken,
  sendCalendarIntent,
  sendStudyGoal,
  resolveApproval,
  setToken,
  type Approval,
  type CalendarIntent,
  type ResearchQuery,
  type StudyGoalDetail,
  type StudyMaterials,
  type StudyModule,
  type StudyGoalSummary,
} from "../api";

const POLL_INTERVAL_MS = 4000;

interface DomainDef {
  name: string;
  cx: number;
  cy: number;
  n: number;
}

interface FieldNode {
  domain: number;
  x: number;
  y: number;
  baseX: number;
  baseY: number;
  phase: number;
  speed: number;
  r: number;
}

interface Pulse {
  a: FieldNode;
  b: FieldNode;
  t: number;
  speed: number;
}

interface QueueItem {
  name: string;
  agent: string;
  status: string;
  pending: boolean;
}

interface RosterItem {
  name: string;
  task: string;
  active: boolean;
}

const DOMAINS: DomainDef[] = [
  { name: "CALENDAR", cx: 0.16, cy: 0.28, n: 7 },
  { name: "HOME", cx: 0.5, cy: 0.16, n: 6 },
  { name: "RESEARCH", cx: 0.82, cy: 0.3, n: 8 },
  { name: "STUDY", cx: 0.2, cy: 0.72, n: 7 },
  { name: "FINANCE", cx: 0.52, cy: 0.82, n: 6 },
  { name: "JOBS", cx: 0.8, cy: 0.7, n: 8 },
];

const QUEUE_SEED: QueueItem[] = [
  { name: "Apply to 2 more roles matching your criteria", agent: "Jobs", status: "In progress", pending: false },
  { name: "Book flights for Dec trip", agent: "Calendar", status: "Waiting on you", pending: true },
  { name: "Review subscription spend for the month", agent: "Finance", status: "Queued", pending: false },
  { name: "Order birthday gift, arrive by Sat", agent: "Home", status: "In progress", pending: false },
  { name: "Summarize onboarding doc for new hire", agent: "Research", status: "Queued", pending: false },
  { name: "Review flashcards — System Design, set 3", agent: "Study", status: "Waiting on you", pending: true },
  { name: "Follow up on Northwind application (day 5)", agent: "Jobs", status: "Queued", pending: false },
  { name: "Compile weekly digest for Monday", agent: "Chief of Staff", status: "Queued", pending: false },
];

const ROSTER_SEED: RosterItem[] = [
  { name: "Calendar Agent", task: "holding focus blocks", active: true },
  { name: "Home Agent", task: "tracking 1 delivery", active: true },
  { name: "Research Agent", task: "reading 3 articles", active: true },
  { name: "Study Agent", task: "tracking System Design course", active: true },
  { name: "Finance Agent", task: "watching for anomalies", active: true },
  { name: "Jobs Agent", task: "2 applications in progress", active: true },
];

function pad(n: number): string {
  return n.toString().padStart(2, "0");
}

export function initDashboard(): () => void {
  let cancelled = false;
  const timers: Array<ReturnType<typeof setInterval> | ReturnType<typeof setTimeout>> = [];
  let rafId = 0;

  /* ---------- CLOCK ---------- */
  const clockEl = document.getElementById("clock")!;
  function tick(): void {
    const d = new Date();
    clockEl.textContent = d.toLocaleTimeString("en-GB");
  }
  tick();
  timers.push(setInterval(tick, 1000));

  /* ---------- FIELD MAP CANVAS ---------- */
  const canvas = document.getElementById("fieldCanvas") as HTMLCanvasElement;
  const ctx = canvas.getContext("2d")!;
  const fieldWrap = canvas.parentElement as HTMLElement;

  function resize(): void {
    const rect = fieldWrap.getBoundingClientRect();
    canvas.width = rect.width * devicePixelRatio;
    canvas.height = rect.height * devicePixelRatio;
    canvas.style.width = rect.width + "px";
    canvas.style.height = rect.height + "px";
    ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  }

  let nodes: FieldNode[] = [];
  function initNodes(): void {
    const rect = fieldWrap.getBoundingClientRect();
    nodes = [];
    DOMAINS.forEach((d, di) => {
      for (let i = 0; i < d.n; i++) {
        const angle = Math.random() * Math.PI * 2;
        const rad = Math.random() * Math.min(rect.width, rect.height) * 0.11;
        const baseX = d.cx * rect.width + Math.cos(angle) * rad;
        const baseY = d.cy * rect.height + Math.sin(angle) * rad;
        nodes.push({
          domain: di,
          x: baseX,
          y: baseY,
          baseX,
          baseY,
          phase: Math.random() * Math.PI * 2,
          speed: 0.4 + Math.random() * 0.6,
          r: 1.2 + Math.random() * 1.8,
        });
      }
    });
  }

  let pulses: Pulse[] = [];
  function spawnPulse(): void {
    if (nodes.length < 2) return;
    const a = nodes[Math.floor(Math.random() * nodes.length)];
    let b: FieldNode;
    if (Math.random() < 0.7) {
      const sameDomain = nodes.filter((n) => n.domain === a.domain && n !== a);
      b = sameDomain[Math.floor(Math.random() * sameDomain.length)] ?? nodes[Math.floor(Math.random() * nodes.length)];
    } else {
      b = nodes[Math.floor(Math.random() * nodes.length)];
    }
    pulses.push({ a, b, t: 0, speed: 0.006 + Math.random() * 0.006 });
  }
  timers.push(setInterval(spawnPulse, 380));

  function draw(t: number): void {
    if (cancelled) return;
    const rect = fieldWrap.getBoundingClientRect();
    ctx.clearRect(0, 0, rect.width, rect.height);

    nodes.forEach((n) => {
      n.x = n.baseX + Math.sin(t * 0.0003 * n.speed + n.phase) * 6;
      n.y = n.baseY + Math.cos(t * 0.00025 * n.speed + n.phase) * 6;
    });

    ctx.lineWidth = 0.6;
    DOMAINS.forEach((_d, di) => {
      const clusterNodes = nodes.filter((n) => n.domain === di);
      for (let i = 0; i < clusterNodes.length; i++) {
        for (let j = i + 1; j < clusterNodes.length; j++) {
          const a = clusterNodes[i];
          const b = clusterNodes[j];
          const dist = Math.hypot(a.x - b.x, a.y - b.y);
          if (dist < 70) {
            ctx.strokeStyle = `rgba(212,161,48,${0.09 * (1 - dist / 70)})`;
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
          }
        }
      }
    });

    pulses.forEach((p) => {
      p.t += p.speed;
      const x = p.a.x + (p.b.x - p.a.x) * p.t;
      const y = p.a.y + (p.b.y - p.a.y) * p.t;
      ctx.strokeStyle = "rgba(212,161,48,0.18)";
      ctx.lineWidth = 0.7;
      ctx.beginPath();
      ctx.moveTo(p.a.x, p.a.y);
      ctx.lineTo(p.b.x, p.b.y);
      ctx.stroke();
      ctx.fillStyle = "#e8c869";
      ctx.beginPath();
      ctx.arc(x, y, 1.8, 0, Math.PI * 2);
      ctx.shadowColor = "#d4a130";
      ctx.shadowBlur = 8;
      ctx.fill();
      ctx.shadowBlur = 0;
    });
    pulses = pulses.filter((p) => p.t < 1);

    nodes.forEach((n) => {
      ctx.fillStyle = "rgba(237,230,214,0.75)";
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fill();
    });

    rafId = requestAnimationFrame(draw);
  }

  function layoutLabels(): void {
    fieldWrap.querySelectorAll(".field-label").forEach((el) => el.remove());
    const rect = fieldWrap.getBoundingClientRect();
    DOMAINS.forEach((d) => {
      const el = document.createElement("div");
      el.className = "field-label";
      el.textContent = d.name;
      el.style.left = d.cx * rect.width - 30 + "px";
      el.style.top = d.cy * rect.height - 34 + "px";
      fieldWrap.appendChild(el);
    });
  }

  function initField(): void {
    resize();
    initNodes();
    layoutLabels();
    rafId = requestAnimationFrame(draw);
  }
  initField();

  const resizeHandler = (): void => {
    resize();
    initNodes();
    layoutLabels();
  };
  window.addEventListener("resize", resizeHandler);

  /* ---------- LIVE DATA (approvals + run log) ---------- */
  // Rows come from the DB (agent- and user-written text), so everything here
  // is rendered with textContent, never innerHTML.
  const approvalsList = document.getElementById("approvalsList")!;
  const approvalCount = document.getElementById("approvalCount")!;
  const logFeed = document.getElementById("logFeed")!;

  function el(tag: string, className: string, text?: string): HTMLElement {
    const node = document.createElement(tag);
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function showNotice(message: string, askForToken: boolean): void {
    approvalCount.textContent = "offline";
    approvalsList.replaceChildren();
    const body = el("div", "approval-body");
    body.appendChild(el("p", "sub", message));
    if (askForToken) {
      const form = document.createElement("form");
      form.className = "approval-actions";
      const input = document.createElement("input");
      input.type = "password";
      input.className = "token-input";
      input.placeholder = "Dashboard token";
      input.autocomplete = "off";
      const save = el("button", "btn approve", "Save");
      form.append(input, save);
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        setToken(input.value.trim());
        void refresh();
      });
      body.appendChild(form);
    }
    const item = el("div", "approval-item");
    item.appendChild(body);
    approvalsList.appendChild(item);
  }

  function renderApprovals(approvals: Approval[]): void {
    approvalCount.textContent = approvals.length + " pending";
    approvalsList.replaceChildren();
    if (approvals.length === 0) {
      const item = el("div", "approval-item");
      item.appendChild(el("p", "sub", "Nothing waiting on you."));
      approvalsList.appendChild(item);
      return;
    }
    approvals.forEach((a) => {
      const item = el("div", "approval-item");
      item.appendChild(el("span", "approval-tag", (a.agent ?? "system").toUpperCase()));
      const body = el("div", "approval-body");
      body.appendChild(el("p", "title", a.title));
      if (a.detail) body.appendChild(el("p", "sub detail", a.detail));
      const actions = el("div", "approval-actions");
      (["approve", "skip"] as const).forEach((decision) => {
        const btn = el("button", `btn ${decision}`, decision === "approve" ? "Approve" : "Skip");
        btn.addEventListener("click", () => {
          actions.querySelectorAll("button").forEach((b) => ((b as HTMLButtonElement).disabled = true));
          resolveApproval(a.id, decision)
            .then(() => item.classList.add("gone"))
            // 409 = already resolved elsewhere; the refresh below shows the truth.
            .catch((err: unknown) => console.error("resolve failed", err))
            .finally(() => void refresh());
        });
        actions.appendChild(btn);
      });
      body.appendChild(actions);
      item.appendChild(body);
      approvalsList.appendChild(item);
    });
  }

  function describeQuery(q: ResearchQuery): string {
    switch (q.status) {
      case "sent":
        return `searched "${q.query}" — ${q.result_count ?? 0} results`;
      case "approved_sent":
        return `approved, searched "${q.query}" — ${q.result_count ?? 0} results`;
      case "pending_approval":
        return `held for approval (${q.pii_flags.join(", ")}): "${q.query}"`;
      case "skipped":
        return `skipped by you, never sent: "${q.query}"`;
      case "failed":
        return `failed: ${q.error ?? "unknown error"}`;
    }
  }

  let lastLogKey = "";
  function renderLog(queries: ResearchQuery[]): void {
    // Skip the re-render (and its fade-in) when nothing changed since the last poll.
    const key = queries.map((q) => `${q.id}:${q.status}`).join(",");
    if (key === lastLogKey) return;
    lastLogKey = key;
    logFeed.replaceChildren();
    // api returns newest first; the feed reads oldest to newest.
    [...queries].reverse().forEach((q) => {
      const d = new Date(q.created_at);
      const line = el("div", "log-line");
      line.appendChild(el("span", "t", `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`));
      line.appendChild(el("span", "agent", (q.agent ?? "research").toUpperCase()));
      line.appendChild(document.createTextNode(" — " + describeQuery(q)));
      logFeed.appendChild(line);
    });
    if (queries.length === 0) logFeed.appendChild(el("div", "log-line", "No research queries yet."));
    logFeed.scrollTop = logFeed.scrollHeight;
  }

  /* ---------- ASK THE CALENDAR AGENT ---------- */
  const askForm = document.getElementById("askForm") as HTMLFormElement;
  const askInput = document.getElementById("askInput") as HTMLInputElement;
  const askHistory = document.getElementById("askHistory")!;
  const ASK_STATE: Record<CalendarIntent["status"], string> = {
    pending: "… thinking",
    drafted: "✓ drafted — approve it above",
    failed: "✕ not drafted",
  };

  let lastAskKey: string | null = null;
  function renderIntents(intents: CalendarIntent[]): void {
    const key = intents.map((i) => `${i.id}:${i.status}`).join(",");
    if (key === lastAskKey) return;
    lastAskKey = key;
    askHistory.replaceChildren();
    intents.forEach((intent) => {
      const line = el("div", `ask-line ${intent.status}`);
      line.appendChild(el("span", "state", ASK_STATE[intent.status]));
      line.appendChild(document.createTextNode(intent.text));
      if (intent.status === "failed" && intent.error) line.appendChild(el("span", "why", intent.error));
      askHistory.appendChild(line);
    });
  }

  const onAskSubmit = (event: Event): void => {
    event.preventDefault();
    const text = askInput.value.trim();
    if (!text) return;
    const submit = askForm.querySelector("button") as HTMLButtonElement;
    submit.disabled = true;
    sendCalendarIntent(text)
      .then(() => {
        askInput.value = "";
        void refresh();
      })
      .catch((err: unknown) => {
        // Show the failure in place; the sentence stays in the box to retry.
        const line = el("div", "ask-line failed");
        line.appendChild(el("span", "state", "✕ not sent"));
        line.appendChild(document.createTextNode(err instanceof Error ? err.message : "Request failed"));
        askHistory.prepend(line);
        lastAskKey = null;
      })
      .finally(() => (submit.disabled = false));
  };
  askForm.addEventListener("submit", onAskSubmit);

  /* ---------- STUDY AGENT ---------- */
  const studyForm = document.getElementById("studyForm") as HTMLFormElement;
  const studyInput = document.getElementById("studyInput") as HTMLInputElement;
  const studyGoals = document.getElementById("studyGoals")!;
  const STUDY_STATE: Record<StudyGoalSummary["status"], string> = {
    pending: "… researching",
    planned: "✓ plan ready",
    failed: "✕ no plan",
  };
  let openGoalId: number | null = null;

  // Sources come from the open web: only ever link to plain http(s) URLs.
  function safeLink(url: string, label: string): HTMLElement {
    let ok = false;
    try {
      ok = ["http:", "https:"].includes(new URL(url).protocol);
    } catch {
      ok = false;
    }
    if (!ok) return el("span", "", label);
    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = label;
    return link;
  }

  function sourceList(sources: Array<{ id: number; title: string; url: string }>): HTMLElement {
    const box = el("div", "study-sources");
    box.appendChild(el("p", "heading", "Sources"));
    sources.forEach((src) => {
      const line = el("div", "");
      line.appendChild(document.createTextNode(`[${src.id}] `));
      line.appendChild(safeLink(src.url, src.title || src.url));
      box.appendChild(line);
    });
    return box;
  }

  function renderCards(materials: StudyMaterials): HTMLElement {
    const box = el("div", "study-work");
    materials.cards.forEach((card) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "study-card";
      item.appendChild(document.createTextNode(card.front));
      item.appendChild(el("span", "hint", "click to flip"));
      item.appendChild(el("span", "back", card.back));
      item.addEventListener("click", () => item.classList.toggle("open"));
      box.appendChild(item);
    });
    return box;
  }

  function renderQuiz(materials: StudyMaterials): HTMLElement {
    const box = el("div", "study-work");
    const total = materials.questions.length;
    let index = 0;
    let score = 0;

    function finish(): void {
      box.replaceChildren();
      box.appendChild(el("p", "quiz-score", `Score: ${score} / ${total}`));
      const again = el("button", "btn approve", "Try again") as HTMLButtonElement;
      again.type = "button";
      again.addEventListener("click", () => {
        index = 0;
        score = 0;
        show();
      });
      box.appendChild(again);
      if (materials.module.materials_sources.length > 0) {
        box.appendChild(sourceList(materials.module.materials_sources));
      }
    }

    function show(): void {
      const q = materials.questions[index];
      box.replaceChildren();
      box.appendChild(el("p", "quiz-progress", `Question ${index + 1} of ${total}`));
      box.appendChild(el("p", "quiz-question", q.question));
      const feedback = el("div", "");
      const buttons = q.options.map((option, i) => {
        const button = el("button", "quiz-option", option) as HTMLButtonElement;
        button.type = "button";
        button.addEventListener("click", () => {
          buttons.forEach((b) => (b.disabled = true));
          answerStudyQuestion(q.id, i)
            .then((result) => {
              if (result.correct) score += 1;
              buttons[result.correct_index].classList.add("right");
              if (!result.correct) button.classList.add("wrong");
              if (result.explanation) feedback.appendChild(el("p", "quiz-explain", result.explanation));
              const isLast = index === total - 1;
              const next = el("button", "btn approve", isLast ? "See score" : "Next") as HTMLButtonElement;
              next.type = "button";
              next.addEventListener("click", () => {
                index += 1;
                if (isLast) finish();
                else show();
              });
              feedback.appendChild(next);
            })
            .catch((err: unknown) => {
              // Nothing was recorded; let me answer again.
              buttons.forEach((b) => (b.disabled = false));
              feedback.replaceChildren(el("p", "why", err instanceof Error ? err.message : "Could not check the answer"));
            });
        });
        box.appendChild(button);
        return button;
      });
      box.appendChild(feedback);
    }

    show();
    return box;
  }

  // Buttons under one module: ask for material, or open what is there.
  function renderModuleActions(m: StudyModule, reload: () => void): HTMLElement {
    const wrap = el("div", "");
    const actions = el("div", "study-actions");
    wrap.appendChild(actions);

    if (m.materials_status === "pending") {
      actions.appendChild(el("span", "busy", "… writing cards and questions"));
      return wrap;
    }
    if (m.materials_status === "ready") {
      const work = el("div", "");
      let showing: "cards" | "quiz" | null = null;
      const open = (kind: "cards" | "quiz"): void => {
        if (showing === kind) {
          showing = null;
          work.replaceChildren();
          return;
        }
        showing = kind;
        work.replaceChildren(el("p", "busy", "Loading…"));
        fetchStudyMaterials(m.id)
          .then((materials) => {
            if (showing !== kind) return;
            work.replaceChildren(kind === "cards" ? renderCards(materials) : renderQuiz(materials));
          })
          .catch((err: unknown) => {
            work.replaceChildren(el("p", "why", err instanceof Error ? err.message : "Could not load"));
          });
      };
      (["cards", "quiz"] as const).forEach((kind) => {
        const button = el("button", "btn approve", kind === "cards" ? "Cards" : "Quiz") as HTMLButtonElement;
        button.type = "button";
        button.addEventListener("click", () => open(kind));
        actions.appendChild(button);
      });
      // Rewriting replaces this module's cards, questions and recorded answers.
      const redo = el("button", "btn skip", "Regenerate") as HTMLButtonElement;
      redo.type = "button";
      redo.addEventListener("click", () => {
        redo.disabled = true;
        requestStudyMaterials(m.id)
          .then(reload)
          .catch((err: unknown) => {
            redo.disabled = false;
            actions.appendChild(el("span", "why", err instanceof Error ? err.message : "Request failed"));
          });
      });
      actions.appendChild(redo);
      wrap.appendChild(work);
      return wrap;
    }

    const generate = el("button", "btn approve", "Generate cards & quiz") as HTMLButtonElement;
    generate.type = "button";
    generate.addEventListener("click", () => {
      generate.disabled = true;
      requestStudyMaterials(m.id)
        .then(reload)
        .catch((err: unknown) => {
          generate.disabled = false;
          actions.appendChild(el("span", "why", err instanceof Error ? err.message : "Request failed"));
        });
    });
    actions.appendChild(generate);
    if (m.materials_status === "failed" && m.materials_error) {
      actions.appendChild(el("span", "why", m.materials_error));
    }
    return wrap;
  }

  // The action area of each module, so a status change can redraw just that
  // module and leave any open cards or quiz in the others alone.
  type ModuleSlots = Map<number, { status: StudyModule["materials_status"]; node: HTMLElement }>;

  function renderPlan(detail: StudyGoalDetail, reload: () => void, slots: ModuleSlots): HTMLElement {
    const box = el("div", "study-plan");
    if (detail.goal.overview) box.appendChild(el("p", "overview", detail.goal.overview));

    if (detail.goal.facts.length > 0) {
      const facts = el("div", "study-facts");
      detail.goal.facts.forEach((f) => {
        const fact = el("div", "");
        fact.appendChild(el("span", "label", f.label));
        fact.appendChild(el("span", "value", f.value));
        facts.appendChild(fact);
      });
      box.appendChild(facts);
    }

    detail.modules.forEach((m) => {
      const module = el("div", "study-module");
      const head = el("div", "");
      const hours = m.est_hours === null ? "" : ` · ${Number(m.est_hours)}h`;
      head.appendChild(el("span", "when", `WEEK ${m.week ?? "?"}${hours}`));
      head.appendChild(el("span", "title", `${m.position}. ${m.title}`));
      module.appendChild(head);
      if (m.summary) module.appendChild(el("p", "", m.summary));
      if (m.topics.length > 0) {
        const list = el("ul", "topics");
        m.topics.forEach((t) => list.appendChild(el("li", "", t)));
        module.appendChild(list);
      }
      if (m.source_ids.length > 0) {
        module.appendChild(el("p", "cites", "Sources: " + m.source_ids.map((i) => `[${i}]`).join(" ")));
      }
      const actions = renderModuleActions(m, reload);
      slots.set(m.id, { status: m.materials_status, node: actions });
      module.appendChild(actions);
      box.appendChild(module);
    });

    if (detail.goal.sources.length > 0) box.appendChild(sourceList(detail.goal.sources));
    box.appendChild(
      el("p", "study-note", "Written by AI from the sources above. Check exam details against the official site."),
    );
    return box;
  }

  let lastStudyKey: string | null = null;
  function renderStudyGoals(goals: StudyGoalSummary[]): void {
    const key = goals.map((g) => `${g.id}:${g.status}`).join(",") + `|${openGoalId}`;
    if (key === lastStudyKey) return;
    lastStudyKey = key;
    studyGoals.replaceChildren();
    goals.forEach((goal) => {
      const row = el("div", `study-goal ${goal.status}`);
      const head = document.createElement("button");
      head.type = "button";
      head.className = "study-goal-head";
      head.disabled = goal.status !== "planned";
      head.appendChild(el("span", "state", STUDY_STATE[goal.status]));
      head.appendChild(el("span", "name", goal.title ?? goal.request_text));
      if (goal.status === "planned") {
        head.appendChild(el("span", "meta", `${goal.modules} modules · ${goal.total_weeks ?? "?"} weeks`));
      }
      row.appendChild(head);
      if (goal.status === "failed" && goal.error) row.appendChild(el("p", "why", goal.error));

      head.addEventListener("click", () => {
        openGoalId = openGoalId === goal.id ? null : goal.id;
        renderStudyGoals(goals);
      });
      if (openGoalId === goal.id && goal.status === "planned") {
        const holder = el("div", "study-plan", "Loading…");
        row.appendChild(holder);
        const slots: ModuleSlots = new Map();
        let drawn = false;
        let pollTimer: ReturnType<typeof setTimeout> | undefined;

        const load = (): void => {
          if (cancelled || openGoalId !== goal.id) return;
          // Once drawn, stop if this row has been replaced by a newer render.
          if (drawn && !row.isConnected) return;
          fetchStudyGoal(goal.id)
            .then((detail) => {
              if (!drawn) {
                holder.replaceWith(renderPlan(detail, load, slots));
                drawn = true;
              } else {
                // Redraw only the modules whose status changed.
                detail.modules.forEach((m) => {
                  const slot = slots.get(m.id);
                  if (!slot || slot.status === m.materials_status) return;
                  const fresh = renderModuleActions(m, load);
                  slot.node.replaceWith(fresh);
                  slots.set(m.id, { status: m.materials_status, node: fresh });
                });
              }
              // While the agent is writing material, check back until it is done.
              clearTimeout(pollTimer);
              if (detail.modules.some((m) => m.materials_status === "pending")) {
                pollTimer = setTimeout(load, POLL_INTERVAL_MS);
                timers.push(pollTimer);
              }
            })
            .catch((err: unknown) => {
              if (!drawn) holder.textContent = err instanceof Error ? err.message : "Could not load the plan";
            });
        };
        load();
      }
      studyGoals.appendChild(row);
    });
  }

  const onStudySubmit = (event: Event): void => {
    event.preventDefault();
    const text = studyInput.value.trim();
    if (!text) return;
    const submit = studyForm.querySelector("button") as HTMLButtonElement;
    submit.disabled = true;
    sendStudyGoal(text)
      .then(() => {
        studyInput.value = "";
        void refresh();
      })
      .catch((err: unknown) => {
        const row = el("div", "study-goal failed");
        row.appendChild(el("p", "why", err instanceof Error ? err.message : "Request failed"));
        studyGoals.prepend(row);
        lastStudyKey = null;
      })
      .finally(() => (submit.disabled = false));
  };
  studyForm.addEventListener("submit", onStudySubmit);

  let refreshing = false;
  async function refresh(): Promise<void> {
    if (refreshing || cancelled) return;
    refreshing = true;
    try {
      if (!getToken()) {
        showNotice("Enter the dashboard token to load live data.", true);
        return;
      }
      const [approvals, queries, intents, goals] = await Promise.all([
        fetchPendingApprovals(),
        fetchResearchQueries(),
        fetchCalendarIntents(),
        fetchStudyGoals(),
      ]);
      if (cancelled) return;
      renderApprovals(approvals);
      renderLog(queries);
      renderIntents(intents);
      renderStudyGoals(goals);
    } catch (err) {
      if (cancelled) return;
      const status = err instanceof ApiError ? err.status : 0;
      if (status === 401) showNotice("Token rejected. Enter it again.", true);
      else if (status === 0) showNotice("Can't reach the api. Retrying…", false);
      else showNotice(err instanceof Error ? err.message : "Unexpected error", false);
    } finally {
      refreshing = false;
    }
  }
  void refresh();
  timers.push(setInterval(() => void refresh(), POLL_INTERVAL_MS));

  /* ---------- TASK QUEUE ---------- */
  const queueList = document.getElementById("queueList")!;
  const queueCount = document.getElementById("queueCount")!;
  queueList.innerHTML = "";
  QUEUE_SEED.forEach((q) => {
    const el = document.createElement("div");
    el.className = "queue-item";
    el.innerHTML = `
      <div><span class="name">${q.name}</span><span class="agent">${q.agent}</span></div>
      <span class="queue-badge ${q.pending ? "pending" : ""}">${q.status}</span>`;
    queueList.appendChild(el);
  });
  queueCount.textContent = QUEUE_SEED.length + " open";

  /* ---------- ROSTER ---------- */
  const roster = document.getElementById("roster")!;
  roster.innerHTML = "";
  ROSTER_SEED.forEach((r) => {
    const el = document.createElement("div");
    el.className = "roster-item";
    el.innerHTML = `
      <span class="roster-dot ${r.active ? "active" : "idle"}"></span>
      <div><span class="roster-name">${r.name}</span><span class="roster-task">${r.task}</span></div>`;
    roster.appendChild(el);
  });

  /* ---------- GAUGE ---------- */
  const gaugeArc = document.getElementById("gaugeArc")!;
  const gaugeNum = document.getElementById("gaugeNum")!;
  const circumference = 326.7;
  let load = 0;
  function animateGauge(target: number): void {
    const step = (): void => {
      if (cancelled) return;
      load += (target - load) * 0.08;
      if (Math.abs(target - load) < 0.3) load = target;
      const offset = circumference - (circumference * load) / 100;
      gaugeArc.style.strokeDashoffset = String(offset);
      gaugeNum.textContent = Math.round(load) + "%";
      if (load !== target) requestAnimationFrame(step);
    };
    step();
  }
  timers.push(setTimeout(() => animateGauge(58), 400));

  return function cleanup(): void {
    cancelled = true;
    cancelAnimationFrame(rafId);
    timers.forEach((id) => {
      clearInterval(id);
      clearTimeout(id);
    });
    window.removeEventListener("resize", resizeHandler);
    askForm.removeEventListener("submit", onAskSubmit);
    studyForm.removeEventListener("submit", onStudySubmit);
    fieldWrap.querySelectorAll(".field-label").forEach((el) => el.remove());
  };
}
