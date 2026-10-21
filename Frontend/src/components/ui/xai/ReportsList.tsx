import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, Eye, FileText, RefreshCw } from "lucide-react";
import { env } from "@/config/env";
import { CoverThumb } from "@/components/ui/report/ReportFileCard";
import { ReportViewer } from "@/components/ui/report/ReportViewer";
import { fetchReports, VERDICT, type ReportItem } from "@/components/ui/report/reports";

// The Report tab: reports already generated for the case, to view or download.
// Reports are made by asking the Copilot to "generate the report" (C3 -> C4);
// this tab never generates one itself.

const font: React.CSSProperties = { fontFamily: "'Inter Variable', system-ui, -apple-system, sans-serif" };

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso
    : d.toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
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
    <div style={font}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "0 2px 8px" }}>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
          {items.length} report{items.length === 1 ? "" : "s"}
        </span>
        <button type="button" className="report-icon-btn" onClick={() => void reports.refetch()}
                aria-label="Refresh reports" title="Refresh" style={iconBtn(false)}>
          <RefreshCw size={13} />
        </button>
      </div>
      {/* one card, rows split by hairlines */}
      <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", background: "var(--surface)",
                    overflow: "hidden" }}>
        {items.map((r) => <ReportRow key={r.report_id} report={r} />)}
      </div>
    </div>
  );
}

function ReportRow({ report: r }: { report: ReportItem }) {
  const [viewing, setViewing] = useState(false);
  const v = VERDICT[r.verdict] ?? { label: r.verdict, color: "var(--text-muted)" };
  const url = `${env.c4Base}${r.download_url}`;
  return (
    <div className="report-row" style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 12px" }}>
      <CoverThumb verdictColor={v.color} small />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text-h)" }}>Audit v{r.version}</span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11.5, fontWeight: 500, color: v.color }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: v.color }} />
            {v.label}
          </span>
        </div>
        <div style={{ fontSize: 12, color: "var(--text-soft)", marginTop: 3 }}>{when(r.generated_at)}</div>
      </div>
      <button type="button" onClick={() => setViewing(true)} className="report-icon-btn"
              aria-label="View report" title="View" style={iconBtn(false)}>
        <Eye size={15} />
      </button>
      <a href={`${url}?download=1`} className="report-icon-btn" aria-label="Download report" title="Download"
         style={iconBtn(true)}>
        <Download size={15} />
      </a>
      {viewing && (
        <ReportViewer url={url} title={`Audit report · ${r.audit_id.replace(":v", " v")}`}
                      subtitle={`${r.filename} · PDF`} onClose={() => setViewing(false)} />
      )}
    </div>
  );
}

function iconBtn(primary: boolean): React.CSSProperties {
  return {
    width: 32, height: 32, flexShrink: 0, display: "inline-flex", alignItems: "center", justifyContent: "center",
    borderRadius: 8, cursor: "pointer", textDecoration: "none",
    border: primary ? "1px solid var(--primary)" : "1px solid var(--border)",
    background: primary ? "var(--primary)" : "transparent",
    color: primary ? "var(--on-primary)" : "var(--text-muted)",
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
