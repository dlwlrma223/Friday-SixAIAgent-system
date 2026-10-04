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

async function request<T>(path: string, method: "GET" | "POST" = "GET"): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers: { Authorization: `Bearer ${getToken()}` },
    });
  } catch {
    throw new ApiError(0, "api unreachable");
  }
  const body = (await res.json().catch(() => ({}))) as { message?: string };
  if (!res.ok) throw new ApiError(res.status, body.message ?? `HTTP ${res.status}`);
  return body as T;
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
