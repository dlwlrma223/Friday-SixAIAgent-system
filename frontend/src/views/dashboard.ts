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

interface ApprovalItem {
  tag: string;
  title: string;
  sub: string;
}

interface LogItem {
  agent: string;
  text: string;
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

const APPROVALS_SEED: ApprovalItem[] = [
  { tag: "JOBS", title: "Apply to Frontend Engineer role at Acme Co. — cover letter drafted", sub: "Match score 87% against your CV · closes in 2 days" },
  { tag: "JOBS", title: "Apply to Product Analyst role at Northwind — tailored CV ready", sub: "Match score 74% · salary range within your target" },
  { tag: "FINANCE", title: "Confirm autopay for internet bill — $58.40, due in 3 days", sub: "Vendor: Telus · recurring, no change from last month" },
  { tag: "STUDY", title: "Schedule 90-min review block for System Design course", sub: "You're 2 modules behind your own pace plan" },
  { tag: "HOME", title: "Approve grocery reorder — usual list, 1 item swapped (out of stock)", sub: "Oat milk → almond milk substitution" },
];

const LOG_POOL: LogItem[] = [
  { agent: "JOBS", text: "scanned 34 new postings, 3 matched your criteria" },
  { agent: "JOBS", text: "submitted application to Acme Co. — Frontend Engineer" },
  { agent: "CALENDAR", text: "found a 30-min gap tomorrow, holding for deep work" },
  { agent: "FINANCE", text: "detected duplicate charge from streaming service" },
  { agent: "RESEARCH", text: "summarized 3 articles on your reading list" },
  { agent: "HOME", text: "delivery ETA updated — arriving between 2–4pm" },
  { agent: "STUDY", text: "logged 45 min on System Design course, streak: 6 days" },
  { agent: "STUDY", text: "flagged a topic you keep re-reading — suggests a quiz" },
  { agent: "CHIEF OF STAFF", text: "compiled daily brief, sent to your inbox" },
  { agent: "JOBS", text: "tailored CV bullet points for Product Analyst role" },
  { agent: "CALENDAR", text: "declined a meeting invite that conflicts with focus block" },
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

  /* ---------- APPROVALS ---------- */
  const approvalsData: ApprovalItem[] = [...APPROVALS_SEED];
  const approvalsList = document.getElementById("approvalsList")!;
  const approvalCount = document.getElementById("approvalCount")!;

  function renderApprovals(): void {
    approvalsList.innerHTML = "";
    approvalsData.forEach((a, idx) => {
      const item = document.createElement("div");
      item.className = "approval-item";
      item.innerHTML = `
        <span class="approval-tag">${a.tag}</span>
        <div class="approval-body">
          <p class="title">${a.title}</p>
          <p class="sub">${a.sub}</p>
          <div class="approval-actions">
            <button class="btn approve">Approve</button>
            <button class="btn skip">Skip</button>
          </div>
        </div>`;
      item.querySelectorAll(".btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          item.classList.add("gone");
          setTimeout(() => {
            approvalsData.splice(idx, 1);
            renderApprovals();
          }, 280);
        });
      });
      approvalsList.appendChild(item);
    });
    approvalCount.textContent = approvalsData.length + " pending";
  }
  renderApprovals();

  /* ---------- RUN LOG ---------- */
  const logFeed = document.getElementById("logFeed")!;
  logFeed.innerHTML = "";
  function addLogLine(): void {
    const item = LOG_POOL[Math.floor(Math.random() * LOG_POOL.length)];
    const d = new Date();
    const line = document.createElement("div");
    line.className = "log-line";
    line.innerHTML = `<span class="t">${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}</span><span class="agent">${item.agent}</span> — ${item.text}`;
    logFeed.appendChild(line);
    logFeed.scrollTop = logFeed.scrollHeight;
    while (logFeed.children.length > 40) {
      logFeed.removeChild(logFeed.firstChild!);
    }
  }
  for (let i = 0; i < 8; i++) addLogLine();
  timers.push(setInterval(addLogLine, 2600));

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
    fieldWrap.querySelectorAll(".field-label").forEach((el) => el.remove());
  };
}
