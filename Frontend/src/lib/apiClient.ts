import { env } from "@/config/env";
import type {
  AuditCase,
  AuditDocument,
  AuditResult,
  CaseSummary,
  ChatMessage,
  ChatSession,
  CopilotRequest,
  CopilotResponse,
} from "@/types/audit";
import type { C1Record, DocumentPreview, FieldDecision } from "@/types/review";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(base: string, path: string, init?: RequestInit): Promise<T> {
  if (!base) throw new ApiError(0, "Backend not configured.");
  let r: Response;
  try {
    r = await fetch(`${base}${path}`, init);
  } catch {
    throw new ApiError(0, `Cannot reach ${base}. Is the server running?`);
  }
  if (!r.ok) {
    // FastAPI puts the reason in `detail`; show it instead of a bare status code.
    const body = await r.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail ?? "");
    throw new ApiError(r.status, detail || `Request failed: ${r.status}`);
  }
  return r.json() as Promise<T>;
}

const session = (id?: string) => (id ? `?session_id=${encodeURIComponent(id)}` : "");

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

// Component-03: audit reasoning + Copilot.
export const c3 = {
  cases: () => request<{ cases: CaseSummary[] }>(env.c3Base, "/audit/cases").then((r) => r.cases),
  latest: (caseId: string) =>
    request<AuditResult>(env.c3Base, `/audit/${encodeURIComponent(caseId)}/latest`),
  // With a sessionId the result is also written into that chat.
  run: (body: AuditCase, sessionId?: string) =>
    request<AuditResult>(env.c3Base, `/audit/run${session(sessionId)}`, json(body)),
  // materiality: a new value for the case; omitted keeps the case's current one.
  appendEvidence: (caseId: string, docs: AuditDocument[], sessionId?: string, materiality?: number) =>
    request<AuditResult>(env.c3Base, `/audit/${encodeURIComponent(caseId)}/evidence${session(sessionId)}`,
      json({ docs, ...(materiality != null ? { materiality } : {}) })),
  // Library review of Component-01 documents: preview saves nothing; confirm returns case documents.
  previewC1: (caseId: string, documents: (C1Record & { doc_type?: string })[]) =>
    request<{ documents: DocumentPreview[] }>(env.c3Base, "/audit/intake/c1/preview",
      json({ case_id: caseId, documents })).then((r) => r.documents),
  confirmC1: (caseId: string, documents: (C1Record & {
    doc_type: string; period_year: number; parent_doc_id?: string | null; fields: FieldDecision[];
    name?: string;
  })[]) =>
    request<{ case: AuditCase; issues: string[] }>(env.c3Base, "/audit/intake/c1/confirm",
      json({ case_id: caseId, documents })),
  copilot: (body: CopilotRequest) =>
    request<CopilotResponse>(env.c3Base, "/copilot/query", json(body)),
};

// Component-03 saved chats.
export const chat = {
  sessions: () => request<{ sessions: ChatSession[] }>(env.c3Base, "/chat/sessions").then((r) => r.sessions),
  messages: (sessionId: string, before?: number) =>
    request<{ messages: ChatMessage[] }>(env.c3Base,
      `/chat/${encodeURIComponent(sessionId)}/messages?limit=100${before ? `&before=${before}` : ""}`)
      .then((r) => r.messages),
  clear: (sessionId: string) =>
    request<{ deleted: string }>(env.c3Base, `/chat/${encodeURIComponent(sessionId)}`, { method: "DELETE" }),
};

// Component-01 has its own typed client: src/features/extraction/api.
