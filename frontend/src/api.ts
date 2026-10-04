const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:3001";
const TOKEN_KEY = "friday.dashboardToken";

export interface Approval {
  id: number;
  agent: string | null;
  title: string;
  detail: string | null;
  status: "pending" | "approved" | "skipped";
  created_at: string;
}

export interface ResearchQuery {
  id: number;
  agent: string | null;
  query: string;
  pii_flags: string[];
  status: "sent" | "pending_approval" | "approved_sent" | "skipped" | "failed";
  result_count: number | null;
  error: string | null;
  created_at: string;
}

export interface CalendarIntent {
  id: number;
  text: string;
  status: "pending" | "drafted" | "failed";
  error: string | null;
}

export interface StudyGoalSummary {
  id: number;
  request_text: string;
  title: string | null;
  status: "pending" | "planned" | "failed";
  error: string | null;
  total_weeks: number | null;
  modules: number;
}

export type MaterialsStatus = "none" | "pending" | "ready" | "failed";

export interface StudyMaterials {
  module: {
    id: number;
    materials_status: MaterialsStatus;
    materials_sources: Array<{ id: number; title: string; url: string }>;
  };
  cards: Array<{ id: number; front: string; back: string }>;
  questions: Array<{ id: number; question: string; options: string[] }>;
}

export interface AnswerResult {
  correct: boolean;
  correct_index: number;
  explanation: string | null;
}

export interface StudyModule {
  id: number;
  materials_status: MaterialsStatus;
  materials_error: string | null;
  position: number;
  title: string;
  summary: string | null;
  topics: string[];
  est_hours: string | number | null;
  week: number | null;
  source_ids: number[];
}

export interface StudyGoalDetail {
  goal: {
    id: number;
    title: string | null;
    overview: string | null;
    facts: Array<{ label: string; value: string }>;
    total_weeks: number | null;
    sources: Array<{ id: number; title: string; url: string }>;
  };
  modules: StudyModule[];
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

// Kept in this browser only; never baked into the build.
export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setToken(token: string): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Private mode etc: the token just won't survive a reload.
  }
}

async function request<T>(path: string, method: "GET" | "POST" = "GET", body?: unknown): Promise<T> {
  let res: Response;
  try {
    const headers: Record<string, string> = { Authorization: `Bearer ${getToken()}` };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "api unreachable");
  }
  const data = (await res.json().catch(() => ({}))) as { message?: string };
  if (!res.ok) throw new ApiError(res.status, data.message ?? `HTTP ${res.status}`);
  return data as T;
}

export async function fetchPendingApprovals(): Promise<Approval[]> {
  return (await request<{ approvals: Approval[] }>("/approvals?status=pending")).approvals;
}

export async function fetchResearchQueries(): Promise<ResearchQuery[]> {
  return (await request<{ queries: ResearchQuery[] }>("/research/queries?limit=40")).queries;
}

export async function resolveApproval(id: number, decision: "approve" | "skip"): Promise<void> {
  await request(`/approvals/${id}/${decision}`, "POST");
}

export async function fetchCalendarIntents(): Promise<CalendarIntent[]> {
  return (await request<{ intents: CalendarIntent[] }>("/calendar/intents")).intents;
}

// Only records the sentence: the agent drafts an event, and that still needs approval.
export async function sendCalendarIntent(text: string): Promise<void> {
  await request("/calendar/intents", "POST", { text });
}

export async function fetchStudyGoals(): Promise<StudyGoalSummary[]> {
  return (await request<{ goals: StudyGoalSummary[] }>("/study/goals")).goals;
}

export async function fetchStudyGoal(id: number): Promise<StudyGoalDetail> {
  return request<StudyGoalDetail>(`/study/goals/${id}`);
}

// Only records the goal: the agent researches it and writes the plan.
export async function sendStudyGoal(text: string): Promise<void> {
  await request("/study/goals", "POST", { text });
}

// Queues the request: the agent writes the cards and questions.
export async function requestStudyMaterials(moduleId: number): Promise<void> {
  await request(`/study/modules/${moduleId}/materials`, "POST");
}

export async function fetchStudyMaterials(moduleId: number): Promise<StudyMaterials> {
  return request<StudyMaterials>(`/study/modules/${moduleId}/materials`);
}

// The server checks the answer and records the attempt.
export async function answerStudyQuestion(questionId: number, chosenIndex: number): Promise<AnswerResult> {
  return request<AnswerResult>(`/study/questions/${questionId}/answer`, "POST", { chosen_index: chosenIndex });
}
