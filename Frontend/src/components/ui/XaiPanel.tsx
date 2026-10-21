import { useEffect, useRef, useState } from "react";
import { useUI } from "@/store/ui";
import { env } from "@/config/env";
import { ThinkingTimeline } from "@/components/ui/xai/ThinkingTimeline";
import { ReportsList } from "@/components/ui/xai/ReportsList";
import type { XaiEvent } from "@/components/ui/xai/timeline";

// Every event name Component-04 sends on /xai/stream/{id}.
const XAI_EVENT_TYPES = [
  "pipeline_start", "pipeline_end", "run_start", "run_end",
  "agent_thinking", "agent_done", "agent_error", "step",
  "llm_thinking", "llm_done", "insight_pending", "insight_summary", "trace",
];

/* ── Shared inline style helpers ────────────────────────────────────── */

const fontBase: React.CSSProperties = {
  fontFamily: "'Inter Variable', system-ui, -apple-system, sans-serif",
};


/* ── Main Component ─────────────────────────────────────────────────── */

export function XaiPanel() {
  const { xaiPanelOpen, xaiActiveTab, selectedCase, toggleXaiPanel, setXaiTab, xaiFocus } = useUI();
  // Events of one stream; switching case shows nothing until the new stream replays.
  const [feed, setFeed] = useState<{ stream: string; events: XaiEvent[] }>({ stream: "", events: [] });
  const [connected, setConnected] = useState(false);
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

  if (!xaiPanelOpen) return null;

  return (
    // A card beside the page, below the top bar, with an even gap on every side.
    <aside id="xai-panel" aria-label="Explainability" style={{
      ...fontBase,
      position: "relative",
      margin: "14px 14px 14px 16px",
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
              padding: "8px 16px",
              borderRadius: "var(--radius-pill)",
              fontSize: "14px",
              fontWeight: 600,
              border: "1px solid transparent",
              background: xaiActiveTab === tab
                ? "var(--seg-active-bg)"
                : "transparent",
              color: xaiActiveTab === tab
                ? "var(--seg-active-text)"
                : "var(--text-muted)",
              boxShadow: xaiActiveTab === tab ? "var(--shadow-sm)" : "none",
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
            focus={xaiFocus}
          />
        ) : (
          <ReportsList caseId={selectedCase} />
        )}
      </div>
    </aside>
  );
}
