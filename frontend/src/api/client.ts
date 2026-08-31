import type {
  AuthResponse,
  Claim,
  ClaimEvidenceResponse,
  Conflict,
  CreateResearch,
  DocumentItem,
  DocumentPassage,
  HealthStatus,
  KnowledgeGap,
  AuditEntry,
  KnowledgeGraph,
  KnowledgeSearchResult,
  KnowledgeStatus,
  MonitoringStats,
  Notification,
  ProjectDetail,
  ProjectSummary,
  Question,
  Recommendation,
  Report,
  ResearchAgainRequest,
  ResearchDiff,
  RunSummary,
  MemoryResponse,
  Schedule,
  ScheduleCreate,
  Solution,
  Source,
  Task,
  User,
} from "./types";

const BASE = import.meta.env.VITE_API_URL ?? "/api";
const TOKEN_KEY = "researchmind_token";

// --- Auth token storage ---------------------------------------------------- //
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

/** Raised on a 401 so callers/UI can react (the app listens and redirects). */
export class UnauthorizedError extends Error {}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (res.status === 401) {
    clearToken();
    // Notify the app so it can drop the session and show the login screen.
    window.dispatchEvent(new CustomEvent("auth:unauthorized"));
    throw new UnauthorizedError("Your session has expired. Please sign in again.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  // --- Auth --- //
  register: (email: string, password: string, name: string) =>
    req<AuthResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, name }),
    }),
  login: (email: string, password: string) =>
    req<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => req<User>("/auth/me"),

  health: () => req<HealthStatus>("/health"),
  createResearch: (body: CreateResearch) =>
    req<ProjectDetail>("/research", { method: "POST", body: JSON.stringify(body) }),
  listResearch: () => req<ProjectSummary[]>("/research"),
  getResearch: (id: string) => req<ProjectDetail>(`/research/${id}`),
  start: (id: string) => req(`/research/${id}/start`, { method: "POST" }),
  pause: (id: string) => req(`/research/${id}/pause`, { method: "POST" }),
  resume: (id: string) => req(`/research/${id}/resume`, { method: "POST" }),
  stop: (id: string) => req(`/research/${id}/stop`, { method: "POST" }),
  questions: (id: string) => req<Question[]>(`/research/${id}/questions`),
  addQuestion: (id: string, text: string, priority = 3) =>
    req<Question>(`/research/${id}/questions`, {
      method: "POST",
      body: JSON.stringify({ text, priority }),
    }),
  tasks: (id: string) => req<Task[]>(`/research/${id}/tasks`),
  sources: (id: string) => req<Source[]>(`/research/${id}/sources`),
  claims: (id: string) => req<Claim[]>(`/research/${id}/claims`),
  claimEvidence: (id: string, claimId: string) =>
    req<ClaimEvidenceResponse>(`/research/${id}/claims/${claimId}/evidence`),

  // --- Research Memory + Again + Diff (#4) --- //
  runs: (id: string) => req<RunSummary[]>(`/research/${id}/runs`),
  memory: (id: string) => req<MemoryResponse>(`/research/${id}/memory`),
  researchAgain: (id: string, body: ResearchAgainRequest) =>
    req<ProjectDetail>(`/research/${id}/research-again`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  diff: (id: string, otherId: string) =>
    req<ResearchDiff>(`/research/${id}/diff/${otherId}`),

  // --- Documents (RAG) --- //
  uploadDocument: async (projectId: string, file: File): Promise<DocumentItem> => {
    // Multipart upload — must NOT set Content-Type (the browser adds the boundary).
    const token = getToken();
    const fd = new FormData();
    fd.append("project_id", projectId);
    fd.append("file", file);
    const res = await fetch(`${BASE}/documents`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: fd,
    });
    if (res.status === 401) {
      clearToken();
      window.dispatchEvent(new CustomEvent("auth:unauthorized"));
      throw new UnauthorizedError("Your session has expired. Please sign in again.");
    }
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = (await res.json()).detail ?? detail;
      } catch {
        /* ignore */
      }
      throw new Error(detail);
    }
    return (await res.json()) as DocumentItem;
  },
  listDocuments: (projectId: string) =>
    req<DocumentItem[]>(`/documents?project_id=${encodeURIComponent(projectId)}`),
  deleteDocument: (id: string) =>
    req<{ message: string }>(`/documents/${id}`, { method: "DELETE" }),
  searchDocuments: (projectId: string, query: string, topK?: number) =>
    req<DocumentPassage[]>(`/documents/search`, {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, query, top_k: topK }),
    }),
  conflicts: (id: string) => req<Conflict[]>(`/research/${id}/conflicts`),
  gaps: (id: string) => req<KnowledgeGap[]>(`/research/${id}/gaps`),
  solutions: (id: string) => req<Solution[]>(`/research/${id}/solutions`),
  recommendation: (id: string) =>
    req<Recommendation | null>(`/research/${id}/recommendation`),
  report: (id: string) => req<Report>(`/research/${id}/report`),
  searchKnowledge: (q: string) =>
    req<KnowledgeSearchResult[]>(`/knowledge/search?q=${encodeURIComponent(q)}`),
  knowledgeStatus: () => req<KnowledgeStatus>("/knowledge/status"),
  knowledgeGraph: (id: string) => req<KnowledgeGraph>(`/knowledge/graph/${id}`),
  reindexKnowledge: () =>
    req<{ message: string }>("/knowledge/reindex", { method: "POST" }),
  monitoringStats: () => req<MonitoringStats>("/monitoring/stats"),
  monitoringAudit: () => req<AuditEntry[]>("/monitoring/audit"),

  // --- Scheduled research --- //
  listSchedules: () => req<Schedule[]>("/schedules"),
  createSchedule: (body: ScheduleCreate) =>
    req<Schedule>("/schedules", { method: "POST", body: JSON.stringify(body) }),
  updateSchedule: (id: string, patch: Partial<Schedule>) =>
    req<Schedule>(`/schedules/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  deleteSchedule: (id: string) =>
    req<{ message: string }>(`/schedules/${id}`, { method: "DELETE" }),
  runScheduleNow: (id: string) =>
    req<{ message: string }>(`/schedules/${id}/run-now`, { method: "POST" }),

  // --- Notifications --- //
  listNotifications: (unreadOnly = false) =>
    req<Notification[]>(`/notifications${unreadOnly ? "?unread_only=true" : ""}`),
  unreadCount: () => req<{ unread: number }>("/notifications/unread-count"),
  markNotificationRead: (id: string) =>
    req<{ message: string }>(`/notifications/${id}/read`, { method: "POST" }),
  markAllNotificationsRead: () =>
    req<{ message: string }>("/notifications/read-all", { method: "POST" }),
  deleteNotification: (id: string) =>
    req<{ message: string }>(`/notifications/${id}`, { method: "DELETE" }),
  // EventSource can't send an Authorization header, so the token rides in the query.
  streamUrl: (id: string) => {
    const token = getToken();
    const q = token ? `?token=${encodeURIComponent(token)}` : "";
    return `${BASE}/research/${id}/stream${q}`;
  },
  exportUrl: (id: string, fmt: string) => {
    // The export is opened via <a>/window, so it also carries the token in the query.
    const token = getToken();
    const auth = token ? `&token=${encodeURIComponent(token)}` : "";
    return `${BASE}/research/${id}/export?format=${fmt}${auth}`;
  },
};
