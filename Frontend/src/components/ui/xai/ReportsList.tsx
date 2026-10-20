import { useQuery } from "@tanstack/react-query";
import { Download, ExternalLink, FileText, RefreshCw } from "lucide-react";
import { env } from "@/config/env";

// The Report tab: reports already generated for the case, to view or download.
// Reports are made by asking the Copilot to "generate the report" (C3 -> C4);
// this tab never generates one itself.

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

const font: React.CSSProperties = { fontFamily: "'Inter Variable', system-ui, -apple-system, sans-serif" };

const VERDICT: Record<string, { label: string; color: string }> = {
  clean: { label: "Clean", color: "var(--success)" },
  issues_found: { label: "Issues found", color: "var(--danger)" },
  needs_review: { label: "Needs review", color: "var(--warning)" },
  not_auditable: { label: "Not auditable", color: "var(--text-muted)" },
};

async function fetchReports(caseId: string): Promise<ReportItem[]> {
  const res = await fetch(`${env.c4Base}/report/list/${encodeURIComponent(caseId)}`);
  if (!res.ok) throw new Error(`Component-04 answered ${res.status}`);
  return (await res.json()).reports as ReportItem[];
}

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso
    : d.toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function ReportsList({ caseId }: { caseId: string | null }) {
  const reports = useQuery({
    queryKey: ["c4-reports", caseId],
    queryFn: () => fetchReports(caseId!),
    enabled: Boolean(caseId && env.c4Base),
    refetchInterval: 15_000, // a report asked for in the chat shows up here by itself
    retry: false,
  });

  if (!caseId) {
    return <Empty title="Select a case" text="Reports belong to a case. Open a case chat to see its reports." />;
  }
  if (reports.isLoading) return <Empty title="Loading reports…" text="" />;
  if (reports.isError) {
    return <Empty title="Reports unavailable" text={(reports.error as Error).message} />;
  }
  const items = reports.data ?? [];
  if (!items.length) {
    return (
      <Empty title="No reports yet"
             text={`Ask the Copilot to “generate the report” for ${caseId}. It will appear here to view or download.`} />
    );
  }

  return (
    <div style={{ ...font, display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
          {items.length} report{items.length === 1 ? "" : "s"} for <strong style={{ color: "var(--text-h)" }}>{caseId}</strong>
        </span>
        <button type="button" className="xai-more" onClick={() => void reports.refetch()} aria-label="Refresh reports"
                style={{ ...font, display: "inline-flex", alignItems: "center", gap: 4, padding: "3px 8px", border: "none",
                         borderRadius: 6, background: "none", cursor: "pointer", fontSize: 12, color: "var(--text-muted)" }}>
          <RefreshCw size={12} /> Refresh
        </button>
      </div>
      {items.map((r) => <ReportRow key={r.report_id} report={r} />)}
    </div>
  );
}

function ReportRow({ report: r }: { report: ReportItem }) {
  const v = VERDICT[r.verdict] ?? { label: r.verdict, color: "var(--text-muted)" };
  const url = `${env.c4Base}${r.download_url}`;
  return (
    <div style={{ border: "1px solid var(--border-strong)", borderRadius: "var(--radius)", background: "var(--surface)",
                  padding: "12px 14px" }}>
      <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
        <span style={{ width: 30, height: 30, borderRadius: 8, flexShrink: 0, display: "flex", alignItems: "center",
                       justifyContent: "center", background: "var(--surface-muted)", color: "var(--text-muted)" }}>
          <FileText size={15} strokeWidth={1.7} />
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-h)" }}>Audit v{r.version}</span>
            <span style={{ fontSize: 11, fontWeight: 600, color: v.color, padding: "1px 7px", borderRadius: "var(--radius-pill)",
                           background: `color-mix(in srgb, ${v.color} 12%, transparent)` }}>{v.label}</span>
            {r.score != null && <span style={{ fontSize: 11.5, color: "var(--text-muted)" }}>Score {r.score}</span>}
          </div>
          <div style={{ fontSize: 11.5, color: "var(--text-soft)", marginTop: 2, overflow: "hidden", textOverflow: "ellipsis",
                        whiteSpace: "nowrap" }}>
            {r.report_id} · {when(r.generated_at)} · {Math.max(1, Math.round(r.size_bytes / 1024))} KB
          </div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <a href={url} target="_blank" rel="noreferrer" className="report-btn" style={btn(false)}>
          <ExternalLink size={13} /> View
        </a>
        <a href={`${url}?download=1`} className="report-btn" style={btn(true)}>
          <Download size={13} /> Download
        </a>
      </div>
    </div>
  );
}

function btn(primary: boolean): React.CSSProperties {
  return {
    ...font, display: "inline-flex", alignItems: "center", gap: 6, padding: "6px 12px", borderRadius: 8,
    fontSize: 12.5, fontWeight: 500, textDecoration: "none", cursor: "pointer",
    border: primary ? "1px solid var(--primary)" : "1px solid var(--border-strong)",
    background: primary ? "var(--primary)" : "transparent",
    color: primary ? "var(--bg)" : "var(--text-h)",
  };
}

function Empty({ title, text }: { title: string; text: string }) {
  return (
    <div style={{ ...font, textAlign: "center", padding: "44px 18px", color: "var(--text-soft)" }}>
      <FileText size={26} strokeWidth={1.2} color="var(--border-strong)" style={{ marginBottom: 12 }} />
      <p style={{ fontSize: 13, fontWeight: 500, color: "var(--text-muted)" }}>{title}</p>
      {text && <p style={{ fontSize: 12, lineHeight: 1.55, marginTop: 6 }}>{text}</p>}
    </div>
  );
}
