import { useEffect, useRef, useState } from "react";
import { useUI } from "@/store/ui";
import { env } from "@/config/env";
import { ThinkingTimeline } from "@/components/ui/xai/ThinkingTimeline";
import type { XaiEvent } from "@/components/ui/xai/timeline";

// Every event name Component-04 sends on /xai/stream/{id}.
const XAI_EVENT_TYPES = [
  "pipeline_start", "pipeline_end", "run_start", "run_end",
  "agent_thinking", "agent_done", "agent_error", "step",
  "llm_thinking", "llm_done", "insight_summary", "trace",
];

/* ── Shared inline style helpers ────────────────────────────────────── */

const fontBase: React.CSSProperties = {
  fontFamily: "'Inter Variable', system-ui, -apple-system, sans-serif",
};

const monoFont: React.CSSProperties = {
  fontFamily: "'JetBrains Mono Variable', monospace",
};


/* ── Main Component ─────────────────────────────────────────────────── */

export function XaiPanel() {
  const { xaiPanelOpen, xaiActiveTab, selectedCase, toggleXaiPanel, setXaiTab } = useUI();
  // Events of one stream; switching case shows nothing until the new stream replays.
  const [feed, setFeed] = useState<{ stream: string; events: XaiEvent[] }>({ stream: "", events: [] });
  const [connected, setConnected] = useState(false);
  const [reportHtml, setReportHtml] = useState<string | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const evtSourceRef = useRef<EventSource | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Follow new steps only while the reader is at the bottom (not while they look back).
  const pinned = useRef(true);
  useEffect(() => {
    const el = scrollRef.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [feed]);

  // The SSE stream ID: selected case, or the general session for copilot chats
  const { generalSessionId } = useUI();
  const streamId = selectedCase || generalSessionId;
  const events = feed.stream === streamId ? feed.events : [];

  // SSE connection for live XAI traces. On every (re)connect C04 first replays
  // the stream's recent history, so the list is rebuilt from scratch on open.
  useEffect(() => {
    if (!xaiPanelOpen || !streamId || !env.c4Base) return;

    const es = new EventSource(`${env.c4Base}/xai/stream/${encodeURIComponent(streamId)}`);
    evtSourceRef.current = es;

    // Events arrive in bursts (a few hundred steps per audit): batch them per frame.
    let pending: XaiEvent[] = [];
    let frame = 0;

    es.onopen = () => {
      setConnected(true);
      pending = []; // anything left from a dropped connection is replayed again
      setFeed({ stream: streamId, events: [] });
    };
    es.onerror = () => setConnected(false);
    const handleEvent = (e: MessageEvent) => {
      try {
        pending.push(JSON.parse(e.data) as XaiEvent);
      } catch {
        return;
      }
      if (!frame) {
        frame = requestAnimationFrame(() => {
          const batch = pending;
          pending = [];
          frame = 0;
          setFeed((prev) => ({
            stream: streamId,
            events: prev.stream === streamId ? [...prev.events, ...batch] : batch,
          }));
        });
      }
    };
    XAI_EVENT_TYPES.forEach((t) => es.addEventListener(t, handleEvent));
    es.onmessage = handleEvent;

    return () => {
      if (frame) cancelAnimationFrame(frame);
      es.close();
      evtSourceRef.current = null;
      setConnected(false);
    };
  }, [xaiPanelOpen, streamId]);

  // Generate report
  const handleGenerateReport = async () => {
    if (!selectedCase || !env.c4Base) return;
    setReportLoading(true);
    try {
      const res = await fetch(`${env.c4Base}/report/generate/${selectedCase}`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setReportHtml(`<p style="color: var(--success);">Report generated: <strong>${data.filename}</strong></p>
          <p style="margin-top: 8px;"><a href="${env.c4Base}${data.download_url}" target="_blank" style="color: var(--info); text-decoration: underline;">Download PDF</a></p>`);
      } else {
        setReportHtml(`<p style="color: var(--danger);">Failed to generate report.</p>`);
      }
    } catch {
      setReportHtml(`<p style="color: var(--danger);">Could not reach C04 server.</p>`);
    } finally {
      setReportLoading(false);
    }
  };

  if (!xaiPanelOpen) return null;

  return (
    // A card beside the page, below the top bar, with an even gap on every side.
    <aside id="xai-panel" aria-label="Explainability" style={{
      ...fontBase,
      position: "relative",
      margin: "12px 12px 12px 0",
      width: "368px",
      flexShrink: 0,
      background: "var(--surface)",
      border: "1px solid var(--border-strong)",
      borderRadius: "var(--radius-lg)",
      display: "flex",
      flexDirection: "column",
      overflow: "hidden",
      boxShadow: "var(--shadow-md)",
      animation: "xai-slide-in 0.25s ease-out",
    }}>
      {/* ── Header ── */}
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        margin: "0 18px",
        padding: "16px 0 14px",
        borderBottom: "1px solid var(--border-light)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{
            fontSize: "15px", fontWeight: 600, color: "var(--text-h)",
            letterSpacing: "-0.01em",
          }}>Explainability</span>
          <span
            title={connected ? "Live" : "Connecting"}
            style={{
              width: "7px", height: "7px", borderRadius: "50%",
              background: connected ? "var(--success)" : "var(--border-strong)",
              transition: "background 0.3s",
            }}
          />
        </div>
        <button
          onClick={toggleXaiPanel}
          aria-label="Close explainability"
          style={{
            background: "none", border: "none", cursor: "pointer",
            color: "var(--text-muted)", padding: "4px",
            borderRadius: "6px", display: "flex",
            alignItems: "center", justifyContent: "center",
            transition: "color 0.15s",
          }}
          onMouseEnter={(e) => (e.currentTarget.style.color = "var(--text-h)")}
          onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text-muted)")}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* ── Tab Switcher ── */}
      <div style={{
        display: "flex",
        gap: "4px",
        margin: "12px 18px 4px",
        padding: "3px",
        borderRadius: "var(--radius-pill)",
        background: "var(--surface-muted)",
      }}>
        {(["thinking", "report"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setXaiTab(tab)}
            style={{
              ...fontBase,
              flex: 1,
              padding: "6px 16px",
              borderRadius: "var(--radius-pill)",
              fontSize: "13px",
              fontWeight: 500,
              border: xaiActiveTab === tab
                ? "1px solid var(--tab-active-border)"
                : "1px solid transparent",
              background: xaiActiveTab === tab
                ? "var(--tab-active-bg)"
                : "transparent",
              color: xaiActiveTab === tab
                ? "var(--text-h)"
                : "var(--text-muted)",
              cursor: "pointer",
              transition: "all 0.2s ease",
            }}
          >
            {tab === "thinking" ? "Thinking" : "Report"}
          </button>
        ))}
      </div>

      {/* ── Content ── */}
      <div ref={scrollRef} onScroll={(e) => {
        const el = e.currentTarget;
        pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      }} style={{
        flex: 1,
        overflowY: "auto",
        padding: "14px 18px 18px",
      }}>
        {xaiActiveTab === "thinking" ? (
          <ThinkingTimeline
            events={events}
            streamId={streamId}
            connected={connected}
          />
        ) : (
          <ReportTab
            selectedCase={selectedCase}
            reportHtml={reportHtml}
            reportLoading={reportLoading}
            onGenerate={handleGenerateReport}
          />
        )}
      </div>
    </aside>
  );
}


/* ── Report Tab ─────────────────────────────────────────────────────── */

function ReportTab({ selectedCase, reportHtml, reportLoading, onGenerate }: {
  selectedCase: string | null;
  reportHtml: string | null;
  reportLoading: boolean;
  onGenerate: () => void;
}) {
  if (!selectedCase) {
    return (
      <div style={{ textAlign: "center", padding: "48px 20px", color: "var(--text-soft)" }}>
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--border)" strokeWidth="1.2" style={{ marginBottom: "14px" }}>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
        </svg>
        <p style={{ fontSize: "13px", lineHeight: 1.6, ...fontBase }}>
          Select a case to generate<br />an audit report
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
      <div style={{
        padding: "14px 16px",
        borderRadius: "var(--radius)",
        background: "var(--surface)",
        border: "1px solid var(--border-strong)",
      }}>
        <p style={{ fontSize: "13px", color: "var(--text)", lineHeight: 1.5, ...fontBase }}>
          Generate a deterministic PDF audit report for case{" "}
          <code style={{ ...monoFont, fontSize: "12px", color: "var(--text-h)" }}>
            {selectedCase}
          </code>.
        </p>
      </div>

      <button
        onClick={onGenerate}
        disabled={reportLoading}
        style={{
          ...fontBase,
          padding: "9px 20px",
          borderRadius: "var(--radius-pill)",
          border: "1px solid var(--border)",
          background: reportLoading ? "var(--surface-muted)" : "var(--primary)",
          color: reportLoading ? "var(--text-muted)" : "var(--surface)",
          fontSize: "13px",
          fontWeight: 500,
          cursor: reportLoading ? "not-allowed" : "pointer",
          transition: "all 0.2s ease",
        }}
      >
        {reportLoading ? "Generating…" : "Generate PDF Report"}
      </button>

      {reportHtml && (
        <div
          style={{
            padding: "14px 16px",
            borderRadius: "var(--radius)",
            background: "var(--surface)",
            border: "1px solid var(--border-strong)",
            fontSize: "13px",
            lineHeight: 1.6,
            ...fontBase,
          }}
          dangerouslySetInnerHTML={{ __html: reportHtml }}
        />
      )}
    </div>
  );
}
