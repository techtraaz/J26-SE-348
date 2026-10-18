import { useEffect, useRef, useState } from "react";
import { useUI } from "@/store/ui";
import { env } from "@/config/env";

/* ── Types ──────────────────────────────────────────────────────────── */

interface TraceEvent {
  event_type: string;
  case_id?: string;
  agent_name?: string;
  detail?: string;
  duration_ms?: number;
  findings_count?: number;
  total_findings?: number;
  status?: string;
  step_index?: number;
  source_timestamp?: string;
  received_at?: string;
  error?: string;
}

/* ── Agent label mapping ────────────────────────────────────────────── */

const agentLabels: Record<string, string> = {
  data_quality: "Data Quality",
  compliance: "Compliance",
  anomaly: "Anomaly Detection",
  reasoning: "Reasoning",
  evidence_validation: "Evidence Validation",
};

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
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [insight, setInsight] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [reportHtml, setReportHtml] = useState<string | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const evtSourceRef = useRef<EventSource | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events]);

  // The SSE stream ID: selected case, or the general session for copilot chats
  const { generalSessionId } = useUI();
  const streamId = selectedCase || generalSessionId;

  // SSE connection for live XAI traces
  useEffect(() => {
    if (!xaiPanelOpen || !streamId || !env.c4Base) return;
    setEvents([]);
    setInsight(null);

    const url = `${env.c4Base}/xai/stream/${streamId}`;
    const es = new EventSource(url);
    evtSourceRef.current = es;

    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);

    const handleEvent = (e: MessageEvent) => {
      try {
        const data: TraceEvent = JSON.parse(e.data);
        if (data.event_type === "insight_summary") {
          setInsight(data.detail || "");
        } else {
          setEvents((prev) => [...prev, data]);
        }
      } catch { /* ignore */ }
    };

    const eventTypes = [
      "pipeline_start", "agent_thinking", "agent_done", "agent_error",
      "llm_thinking", "llm_done", "pipeline_end", "insight_summary", "trace",
    ];
    eventTypes.forEach((t) => es.addEventListener(t, handleEvent));
    es.onmessage = handleEvent;

    return () => {
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
    <div id="xai-panel" style={{
      ...fontBase,
      position: "fixed",
      top: 0,
      right: 0,
      width: "380px",
      height: "100vh",
      background: "var(--bg)",
      borderLeft: "1px solid var(--border-light)",
      display: "flex",
      flexDirection: "column",
      zIndex: 1000,
      boxShadow: "-4px 0 20px rgba(0,0,0,0.05)",
      animation: "xai-slide-in 0.25s ease-out",
    }}>
      {/* ── Header ── */}
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "14px 20px",
        borderBottom: "1px solid var(--border-light)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <div style={{
            width: "6px", height: "6px", borderRadius: "50%",
            background: connected ? "var(--success)" : "var(--border)",
            transition: "background 0.3s",
          }} />
          <span style={{
            fontSize: "13px", fontWeight: 500, color: "var(--text-h)",
            letterSpacing: "-0.01em",
          }}>XAI Inspector</span>
        </div>
        <button
          onClick={toggleXaiPanel}
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
        padding: "10px 20px",
        borderBottom: "1px solid var(--border-light)",
      }}>
        {(["thinking", "report"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setXaiTab(tab)}
            style={{
              ...fontBase,
              flex: 1,
              padding: "7px 16px",
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
      <div ref={scrollRef} style={{
        flex: 1,
        overflowY: "auto",
        padding: "16px 20px",
      }}>
        {xaiActiveTab === "thinking" ? (
          <ThinkingTimeline
            events={events}
            insight={insight}
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
    </div>
  );
}


/* ── Thinking Timeline ──────────────────────────────────────────────── */

function ThinkingTimeline({ events, insight, streamId, connected }: {
  events: TraceEvent[];
  insight: string | null;
  streamId: string;
  connected: boolean;
}) {
  if (events.length === 0 && !insight) {
    return (
      <div style={{ textAlign: "center", padding: "48px 20px", color: "var(--text-soft)" }}>
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--border)" strokeWidth="1.2" style={{ marginBottom: "14px" }}>
          <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
        </svg>
        <p style={{ fontSize: "13px", lineHeight: 1.6, ...fontBase }}>
          {connected ? "Waiting for events…" : "Connecting to XAI stream…"}
        </p>
        <p style={{ fontSize: "11px", marginTop: "8px", color: "var(--text-soft)", ...monoFont }}>
          {streamId}
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1px" }}>
      {events.map((evt, i) => (
        <TimelineEntry key={i} event={evt} />
      ))}

      {insight && (
        <div style={{
          marginTop: "14px",
          padding: "14px 16px",
          borderRadius: "var(--radius)",
          background: "var(--surface)",
          border: "1px solid var(--border-light)",
        }}>
          <div style={{
            fontSize: "11px", fontWeight: 600, textTransform: "uppercase" as const,
            letterSpacing: "0.05em", color: "var(--text-soft)", marginBottom: "8px",
            ...fontBase,
          }}>
            AI Insight
          </div>
          <p style={{ fontSize: "13px", lineHeight: 1.6, color: "var(--text)", ...fontBase }}>
            {insight}
          </p>
        </div>
      )}
    </div>
  );
}



/* ── Single Timeline Entry ──────────────────────────────────────────── */

function TimelineEntry({ event: evt }: { event: TraceEvent }) {
  const agent = evt.agent_name || "";
  const label = agentLabels[agent] || agent || "Pipeline";

  const isStart = evt.event_type === "agent_thinking" || evt.event_type === "pipeline_start";
  const isDone = evt.event_type === "agent_done" || evt.event_type === "pipeline_end";
  const isError = evt.event_type === "agent_error";

  let statusColor = "var(--text-soft)";
  let statusText = "";

  if (isStart) {
    statusColor = "var(--text-muted)";
    statusText = "thinking…";
  } else if (isDone) {
    statusColor = "var(--success)";
    statusText = evt.duration_ms ? `${evt.duration_ms.toFixed(0)}ms` : "done";
  } else if (isError) {
    statusColor = "var(--danger)";
    statusText = "error";
  }

  // Pipeline start/end — compact one-liner
  if (evt.event_type === "pipeline_start" || evt.event_type === "pipeline_end") {
    const isPipeEnd = evt.event_type === "pipeline_end";
    return (
      <div style={{
        padding: "8px 0",
        borderBottom: "1px solid var(--border-light)",
        marginBottom: "4px",
      }}>
        <span style={{ fontSize: "12px", color: "var(--text-muted)", ...fontBase }}>
          {isPipeEnd
            ? `Pipeline complete · ${evt.total_findings ?? 0} finding${(evt.total_findings ?? 0) !== 1 ? "s" : ""}`
            : `Pipeline started · ${evt.detail || ""}`}
        </span>
      </div>
    );
  }

  return (
    <div style={{
      display: "flex",
      alignItems: "flex-start",
      gap: "12px",
      padding: "9px 0",
      borderBottom: "1px solid var(--border-light)",
    }}>
      {/* Dot */}
      <div style={{
        width: "7px", height: "7px", borderRadius: "50%",
        background: isStart ? "var(--text-muted)" : isDone ? "var(--success)" : isError ? "var(--danger)" : "var(--border)",
        marginTop: "5px", flexShrink: 0,
        animation: isStart ? "xai-pulse 1.4s ease-in-out infinite" : "none",
      }} />

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          display: "flex", alignItems: "center",
          justifyContent: "space-between", gap: "8px",
        }}>
          <span style={{
            fontSize: "13px", fontWeight: 500, color: "var(--text-h)", ...fontBase,
          }}>{label}</span>
          <span style={{
            fontSize: "11px", color: statusColor, fontWeight: 500,
            whiteSpace: "nowrap" as const, ...fontBase,
          }}>
            {statusText}
          </span>
        </div>

        {evt.detail && (
          <p style={{
            fontSize: "12px", color: "var(--text-muted)",
            marginTop: "2px", lineHeight: 1.4,
            overflow: "hidden", textOverflow: "ellipsis",
            display: "-webkit-box", WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical" as const,
            ...fontBase,
          }}>{evt.detail}</p>
        )}

        {evt.findings_count != null && evt.findings_count > 0 && (
          <span style={{
            display: "inline-block", marginTop: "4px",
            fontSize: "11px", fontWeight: 500,
            padding: "1px 8px", borderRadius: "var(--radius-pill)",
            background: "var(--accent-bg)", color: "var(--text-muted)",
            ...fontBase,
          }}>
            {evt.findings_count} finding{evt.findings_count !== 1 ? "s" : ""}
          </span>
        )}
      </div>
    </div>
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
        border: "1px solid var(--border-light)",
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
            border: "1px solid var(--border-light)",
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
