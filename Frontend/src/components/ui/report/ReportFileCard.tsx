import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Download, ExternalLink, Eye } from "lucide-react";
import { env } from "@/config/env";
import { fetchReports, VERDICT } from "./reports";
import { ReportViewer } from "./ReportViewer";
import { downloadUrl } from "./reportLink";

// The audit report in a Copilot reply, shown as a file (like Claude's file cards):
// a small cover preview, the report's name, its verdict and size, and a Download
// button with View / Open in new tab. Clicking the card opens the in-app viewer.

const font: React.CSSProperties = { fontFamily: "'Inter Variable', system-ui, -apple-system, sans-serif" };

export function ReportFileCard({ url, filename, caseId }: { url: string; filename: string; caseId: string | null }) {
  const [viewing, setViewing] = useState(false);
  const [menu, setMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // the report's verdict and size, from the same list the Report tab shows
  const reports = useQuery({
    queryKey: ["c4-reports", caseId],
    queryFn: () => fetchReports(caseId!),
    enabled: Boolean(caseId && env.c4Base),
    retry: false,
  });
  const meta = reports.data?.find((r) => r.filename === filename);
  const verdict = meta ? VERDICT[meta.verdict] : undefined;
  const title = `Audit report · ${caseId ?? filename.replace(/\.pdf$/, "")}${meta ? ` v${meta.version}` : ""}`;

  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent) => { if (!menuRef.current?.contains(e.target as Node)) setMenu(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menu]);

  return (
    <>
      <div
        className="report-card"
        role="group"
        aria-label={title}
        onClick={() => setViewing(true)}
        style={{
          ...font, width: "min(460px, 85%)", display: "flex", alignItems: "center", gap: 14, padding: "10px 12px 10px 10px",
          borderRadius: 14, border: "1px solid var(--border-strong)", background: "var(--surface)",
          boxShadow: "var(--shadow-sm)", cursor: "pointer",
        }}
      >
        <CoverThumb verdictColor={verdict?.color} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 500, color: "var(--text-h)", overflow: "hidden",
                        textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 3, fontSize: 12.5,
                        color: "var(--text-muted)", whiteSpace: "nowrap", overflow: "hidden" }}>
            <span>Document · PDF</span>
            {verdict && <span style={{ color: verdict.color, fontWeight: 500 }}>· {verdict.label}</span>}
            {meta && <span>· {Math.max(1, Math.round(meta.size_bytes / 1024))} KB</span>}
          </div>
        </div>

        {/* Download | ▾ (View, Open in new tab) */}
        <div ref={menuRef} onClick={(e) => e.stopPropagation()} style={{ position: "relative", flexShrink: 0 }}>
          <div style={{ display: "flex", alignItems: "stretch", borderRadius: 9, background: "var(--surface-muted)",
                        border: "1px solid var(--border-strong)", overflow: "hidden" }}>
            <a href={downloadUrl(url)} className="report-split" style={splitBtn}>
              <Download size={14} strokeWidth={1.8} /> Download
            </a>
            <button type="button" className="report-split" aria-label="More options" aria-haspopup="menu"
                    aria-expanded={menu} onClick={() => setMenu(!menu)}
                    style={{ ...splitBtn, padding: "0 8px", borderLeft: "1px solid var(--border-strong)" }}>
              <ChevronDown size={14} />
            </button>
          </div>
          {menu && (
            <div role="menu" style={{
              position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 30, minWidth: 170, padding: 4,
              borderRadius: 10, background: "var(--surface)", border: "1px solid var(--border-strong)",
              boxShadow: "var(--shadow-md)",
            }}>
              <button type="button" role="menuitem" className="report-menu-item" style={menuItem}
                      onClick={() => { setMenu(false); setViewing(true); }}>
                <Eye size={14} /> View
              </button>
              <a role="menuitem" href={url} target="_blank" rel="noreferrer" className="report-menu-item"
                 style={menuItem} onClick={() => setMenu(false)}>
                <ExternalLink size={14} /> Open in new tab
              </a>
            </div>
          )}
        </div>
      </div>
      {viewing && <ReportViewer url={url} title={title} subtitle={`${filename} · PDF`} onClose={() => setViewing(false)} />}
    </>
  );
}

/** A miniature of the report's cover page: every NOMOS report opens with the brown band. */
export function CoverThumb({ verdictColor }: { verdictColor?: string }) {
  return (
    <div aria-hidden style={{
      width: 52, height: 66, flexShrink: 0, borderRadius: 5, overflow: "hidden", background: "#fff",
      border: "1px solid var(--border-strong)", boxShadow: "0 1px 3px rgba(0,0,0,0.12)", display: "flex",
      flexDirection: "column",
    }}>
      <div style={{ height: 15, background: "#3d3429", display: "flex", alignItems: "center", padding: "0 4px" }}>
        <span style={{ fontFamily: "Georgia, serif", fontSize: 6.5, fontWeight: 700, color: "#f5f0ea", letterSpacing: 0.2 }}>
          NOMOS
        </span>
      </div>
      <div style={{ height: 1.5, background: "#b07c2e" }} />
      <div style={{ padding: "5px 4px", display: "flex", flexDirection: "column", gap: 3 }}>
        <div style={{ height: 3, width: "70%", background: "#3d3429", borderRadius: 1 }} />
        <div style={{ height: 9, borderRadius: 2, background: "#f3eee7",
                      borderLeft: `2px solid ${verdictColor ?? "#a69d93"}` }} />
        {[90, 75, 85, 60].map((w) => (
          <div key={w} style={{ height: 2, width: `${w}%`, background: "#e3ddd5", borderRadius: 1 }} />
        ))}
      </div>
    </div>
  );
}

const splitBtn: React.CSSProperties = {
  ...font, display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 12px", border: "none",
  background: "transparent", color: "var(--text-h)", fontSize: 13, fontWeight: 500, textDecoration: "none",
  cursor: "pointer",
};

const menuItem: React.CSSProperties = {
  ...font, display: "flex", alignItems: "center", gap: 8, width: "100%", padding: "7px 10px", border: "none",
  borderRadius: 7, background: "transparent", color: "var(--text-h)", fontSize: 13, textDecoration: "none",
  cursor: "pointer", textAlign: "left",
};
