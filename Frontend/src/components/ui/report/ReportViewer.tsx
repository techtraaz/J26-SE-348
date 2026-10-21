import { useEffect } from "react";
import { createPortal } from "react-dom";
import { Download, Maximize2, X } from "lucide-react";
import { downloadUrl } from "./reportLink";

// An in-app PDF viewer (like Claude's file preview): a dark window over the app
// with the report's title, Download, Open full size and Close. The PDF itself is
// shown by the browser's own viewer, served inline by Component-04.

const font: React.CSSProperties = { fontFamily: "'Inter Variable', system-ui, -apple-system, sans-serif" };

export function ReportViewer({ url, title, subtitle, onClose }: {
  url: string;
  title: string;
  subtitle?: string;
  onClose: () => void;
}) {
  // Escape closes; the page behind does not scroll while the viewer is open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      className="report-viewer-scrim"
      style={{
        position: "fixed", inset: 0, zIndex: 2000, display: "flex", alignItems: "center", justifyContent: "center",
        padding: "24px", background: "rgba(4, 18, 44, 0.62)", backdropFilter: "blur(3px)",
      }}
    >
      <div className="report-viewer" style={{
        ...font, width: "min(920px, 100%)", height: "min(92vh, 1200px)", display: "flex", flexDirection: "column",
        background: "#0c2c5f", borderRadius: "14px", overflow: "hidden",
        border: "1px solid rgba(255,255,255,0.08)", boxShadow: "0 24px 64px rgba(0,0,0,0.45)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 14px 12px 20px",
                      borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
          <div style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "baseline", gap: 8 }}>
            <span style={{ fontSize: 15, fontWeight: 500, color: "#ffffff", overflow: "hidden",
                           textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</span>
            <span style={{ fontSize: 13, color: "#9fb9dd", whiteSpace: "nowrap" }}>{subtitle ?? "PDF"}</span>
          </div>
          <a href={downloadUrl(url)} className="viewer-btn" aria-label="Download" data-tip="Download" style={iconBtn}>
            <Download size={17} strokeWidth={1.8} />
          </a>
          <a href={url} target="_blank" rel="noreferrer" className="viewer-btn" aria-label="Open full size"
             style={iconBtn}>
            <Maximize2 size={16} strokeWidth={1.8} />
          </a>
          <button type="button" onClick={onClose} className="viewer-btn" aria-label="Close" style={iconBtn}>
            <X size={18} strokeWidth={1.8} />
          </button>
        </div>
        <iframe
          title={title}
          src={`${url}#toolbar=0&navpanes=0&view=FitH`}
          style={{ flex: 1, width: "100%", border: "none", background: "#08214a" }}
        />
      </div>
    </div>,
    document.body,
  );
}

const iconBtn: React.CSSProperties = {
  width: 34, height: 34, display: "inline-flex", alignItems: "center", justifyContent: "center",
  borderRadius: 8, border: "none", background: "transparent", color: "#c9daf2", cursor: "pointer",
};
