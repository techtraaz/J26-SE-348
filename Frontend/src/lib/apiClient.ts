import { env } from "@/config/env";
import type {
  AuditCase,
  AuditDocument,
  AuditResult,
  CaseSummary,
  CopilotRequest,
  CopilotResponse,
} from "@/types/audit";

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
  run: (body: AuditCase) => request<AuditResult>(env.c3Base, "/audit/run", json(body)),
  appendEvidence: (caseId: string, docs: AuditDocument[]) =>
    request<AuditResult>(env.c3Base, `/audit/${encodeURIComponent(caseId)}/evidence`, json({ docs })),
  intakeC1: (body: unknown) =>
    request<{ case: AuditCase; unmapped_regions: Record<string, number>; issues: string[] }>(
      env.c3Base, "/audit/intake/c1", json(body)),
  copilot: (body: CopilotRequest) => request<CopilotResponse>(env.c3Base, "/copilot/query", json(body)),
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
};
