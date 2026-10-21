import { env } from "@/config/env";

// Reports Component-04 has generated for a case (GET /report/list/{case_id}).

export interface ReportItem {
  report_id: string;
  filename: string;
  audit_id: string;
  version: number;
  verdict: "clean" | "issues_found" | "needs_review" | "not_auditable" | string;
  score: number | null;
  generated_at: string;
  size_bytes: number;
  download_url: string;
}

export const VERDICT: Record<string, { label: string; color: string }> = {
  clean: { label: "Clean", color: "var(--success)" },
  issues_found: { label: "Issues found", color: "var(--danger)" },
  needs_review: { label: "Needs review", color: "var(--warning)" },
  not_auditable: { label: "Not auditable", color: "var(--text-muted)" },
};

export async function fetchReports(caseId: string): Promise<ReportItem[]> {
  const res = await fetch(`${env.c4Base}/report/list/${encodeURIComponent(caseId)}`);
  if (!res.ok) throw new Error(`Component-04 answered ${res.status}`);
  return (await res.json()).reports as ReportItem[];
}
