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
  appendEvidence: (caseId: string, docs: AuditDocument[], sessionId?: string) =>
    request<AuditResult>(env.c3Base, `/audit/${encodeURIComponent(caseId)}/evidence${session(sessionId)}`,
      json({ docs })),
  // Library review of Component-01 documents: preview saves nothing; confirm returns case documents.
  previewC1: (caseId: string, documents: (C1Record & { doc_type?: string })[]) =>
    request<{ documents: DocumentPreview[] }>(env.c3Base, "/audit/intake/c1/preview",
      json({ case_id: caseId, documents })).then((r) => r.documents),
  confirmC1: (caseId: string, documents: (C1Record & {
    doc_type: string; period_year: number; parent_doc_id?: string | null; fields: FieldDecision[];
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

// Component-01: OCR/VLM extraction. Used only when VITE_C1_BASE is set.
const C1 = "/api/v1/documents";
export const c1 = {
  enabled: () => Boolean(env.c1Base),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ id: string }>(env.c1Base, C1, { method: "POST", body: form });
  },
  status: (id: string) =>
    request<{ latest_run: { status: string } | null; error_message: string | null }>(env.c1Base, `${C1}/${id}`),
  extraction: (id: string) => request<Record<string, unknown>>(env.c1Base, `${C1}/${id}/extraction`),
  // The human-verified record (proposed C1 endpoint). null when C1 has none yet.
  verified: (id: string) =>
    request<Record<string, unknown>>(env.c1Base, `${C1}/${id}/verified`).catch((e) => {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }),
};
