import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Ellipsis, PanelLeft, Plus, Trash2, UserRound } from "lucide-react";
import { c3, chat } from "@/lib/apiClient";
import { env } from "@/config/env";
import { useUI } from "@/store/ui";
import { IconButton } from "@/components/ui/IconButton";
import type { CaseSummary } from "@/types/audit";

// The Chat page's sidebar, full height from the top of the window (Claude-style):
// brand and hide button on top, "New case", the cases (one chat each), the account
// at the bottom. Collapses to a narrow rail (Ctrl+B).

// A case in the sidebar: audited (with its latest summary) or started here and not audited yet.
type SidebarCase = { case_id: string; summary: CaseSummary | null };

function timeAgo(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return `${mins}m ago`;
  if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
  return `${Math.round(mins / 1440)}d ago`;
}

function caseMeta(c: CaseSummary): string {
  if (c.status === "not_auditable") return `v${c.version} · not auditable`;
  return `v${c.version} · ${c.findings} finding(s)${c.high ? `, ${c.high} high` : ""}`;
}

export function CasesSidebar() {
  const { selectedCase, setCase, newCase, draftCases, generalSessionId, sidebarOpen: open, toggleSidebar } = useUI();
  const cases = useQuery({ queryKey: ["c3-cases"], queryFn: c3.cases, retry: false });

  const sidebar = useMemo((): SidebarCase[] => {
    const audited = cases.data ?? [];
    const known = new Set(audited.map((c) => c.case_id));
    const drafts = draftCases.filter((id) => !known.has(id)).map((id) => ({ case_id: id, summary: null }));
    return [...drafts, ...audited.map((c) => ({ case_id: c.case_id, summary: c }))];
  }, [cases.data, draftCases]);

  // Ctrl+B (Cmd+B on Mac) shows or hides the sidebar.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "b") {
        e.preventDefault();
        toggleSidebar();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleSidebar]);

  return (
    <aside aria-label="Cases" style={{
      width: open ? "260px" : "56px", flexShrink: 0, height: "100%",
      borderRight: "1px solid var(--border-light)", background: "var(--sidebar-bg)",
      display: "flex", flexDirection: "column", overflow: open ? "hidden" : "visible",
      transition: "width 0.2s ease",
    }}>
      {/* ── Brand + hide (same height as the top bar) ── */}
      <div style={{
        height: "60px", flexShrink: 0, display: "flex", alignItems: "center", gap: "8px",
        padding: open ? "0 12px 0 12px" : "0 12px", justifyContent: open ? "flex-start" : "center",
      }}>
        <IconButton tip={open ? "Hide sidebar" : "Show sidebar"} shortcut="Ctrl+B"
                    tipSide={open ? "bottom" : "right"} onClick={toggleSidebar}>
          <PanelLeft size={18} strokeWidth={1.6} />
        </IconButton>
        {open && (
          <span className="heading-serif" style={{ fontSize: "24px", lineHeight: 1, userSelect: "none" }}>
            NOMOS
          </span>
        )}
      </div>

      {/* ── New case ── */}
      <div style={{ padding: open ? "4px 12px 8px" : "4px 12px 8px", display: "flex",
                    justifyContent: open ? "stretch" : "center" }}>
        {open ? (
          <button type="button" className="side-row" onClick={() => newCase()} style={rowStyle(false)}>
            <span style={{
              width: "24px", height: "24px", borderRadius: "50%", flexShrink: 0,
              background: "var(--surface-muted)", border: "1px solid var(--border-strong)",
              display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-h)",
            }}>
              <Plus size={14} strokeWidth={2} />
            </span>
            <span style={{ fontSize: "13.5px", color: "var(--text-h)", fontWeight: 500 }}>New case</span>
          </button>
        ) : (
          <IconButton tip="New case" tipSide="right" onClick={() => newCase()}>
            <Plus size={18} strokeWidth={1.6} />
          </IconButton>
        )}
      </div>

      {/* ── Cases ── */}
      {open ? (
        <div className="thin-scroll" style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "4px 12px 12px" }}>
          <SessionButton active={selectedCase === null} onClick={() => setCase(null)} sessionId={generalSessionId}
                         title="General questions" meta="rules, standards, what-ifs" />
          <div style={{ fontSize: "12px", color: "var(--text-soft)", padding: "16px 10px 6px", fontWeight: 500 }}>
            Cases
          </div>
          {cases.isError && (
            <p style={{ fontSize: "12px", color: "var(--danger)", margin: "6px 10px" }}>
              Cases unavailable: {(cases.error as Error).message}
            </p>
          )}
          {sidebar.map((c) => (
            <SessionButton key={c.case_id} active={selectedCase === c.case_id} onClick={() => setCase(c.case_id)}
                           sessionId={c.case_id}
                           title={c.case_id} meta={c.summary ? caseMeta(c.summary) : "new · not audited"}
                           right={c.summary ? timeAgo(c.summary.created_at) : ""} />
          ))}
        </div>
      ) : (
        <div style={{ flex: 1 }} />
      )}

      {/* ── Account ── */}
      <div style={{ borderTop: "1px solid var(--border-light)", padding: "10px 12px",
                    display: "flex", justifyContent: open ? "flex-start" : "center" }}>
        <button type="button" className="icon-btn" aria-label="Account" data-tip="Account"
                data-tip-side={open ? "top" : "right"}
                style={{
                  display: "flex", alignItems: "center", gap: "10px", width: open ? "100%" : "36px",
                  height: "40px", padding: open ? "0 8px" : 0, justifyContent: open ? "flex-start" : "center",
                  border: "none", borderRadius: "10px", background: "transparent", cursor: "pointer",
                  color: "var(--text-muted)", fontFamily: "inherit", fontSize: "13px",
                }}>
          <span style={{
            width: "28px", height: "28px", borderRadius: "50%", flexShrink: 0,
            border: "1px solid var(--border-strong)", background: "var(--surface)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <UserRound size={15} strokeWidth={1.6} />
          </span>
          {open && <span style={{ color: "var(--text-h)", fontWeight: 500 }}>Auditor</span>}
        </button>
      </div>
    </aside>
  );
}

function rowStyle(active: boolean): React.CSSProperties {
  return {
    display: "flex", alignItems: "center", gap: "10px", padding: "8px 10px", borderRadius: "10px",
    border: "none", background: active ? "var(--sidebar-active)" : "transparent", cursor: "pointer",
    width: "100%", textAlign: "left", fontFamily: "inherit",
  };
}

function SessionButton({ active, onClick, sessionId, title, meta, right }: {
  active: boolean; onClick: () => void; sessionId: string; title: string; meta: string; right?: string;
}) {
  const [menu, setMenu] = useState(false);
  return (
    <div className={`side-item${menu ? " side-item-menu" : ""}${active ? " side-item-active" : ""}`}
         style={{ position: "relative" }}>
      <button type="button" className={active ? "side-row side-row-active" : "side-row"} onClick={onClick}
              style={{ ...rowStyle(active), paddingRight: "36px" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: "13px", color: "var(--text-h)", fontWeight: active ? 500 : 400, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {title}
          </div>
          <div style={{ fontSize: "11px", color: "var(--text-soft)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{meta}</div>
        </div>
        {right && <span className="side-time" style={{ fontSize: "11px", color: "var(--text-soft)", flexShrink: 0 }}>{right}</span>}
      </button>
      <button type="button" className="side-more" aria-label={`Options for ${title}`} aria-haspopup="menu"
              aria-expanded={menu} onClick={() => setMenu(!menu)}>
        <Ellipsis size={16} strokeWidth={1.8} />
      </button>
      {menu && <ChatMenu sessionId={sessionId} title={title} onClose={() => setMenu(false)} />}
    </div>
  );
}

/** The "..." menu of one chat. Clearing asks once more, since it cannot be undone. */
function ChatMenu({ sessionId, title, onClose }: { sessionId: string; title: string; onClose: () => void }) {
  const qc = useQueryClient();
  const ref = useRef<HTMLDivElement>(null);
  const [confirm, setConfirm] = useState(false);
  const [working, setWorking] = useState(false);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.parentElement?.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  async function clear() {
    setWorking(true);
    try {
      await chat.clear(sessionId); // C3: the chat's messages and its Copilot traces
    } catch {
      // nothing saved yet for this chat
    }
    if (env.c4Base) {
      // C4: the chat's saved reviews and its live history in the Explainability panel
      await fetch(`${env.c4Base}/xai/history/${encodeURIComponent(sessionId)}`, { method: "DELETE" })
        .catch(() => undefined);
    }
    await qc.invalidateQueries({ queryKey: ["chat", sessionId] });
    setWorking(false);
    onClose();
  }

  return (
    <div ref={ref} role="menu" aria-label={`Options for ${title}`} style={{
      position: "absolute", top: "calc(100% - 4px)", right: "6px", zIndex: 30, minWidth: "190px",
      padding: "4px", borderRadius: "10px", background: "var(--surface)",
      border: "1px solid var(--border-strong)", boxShadow: "var(--shadow-md)",
    }}>
      <button type="button" role="menuitem" className="menu-item" disabled={working}
              onClick={() => (confirm ? void clear() : setConfirm(true))}
              style={{
                display: "flex", alignItems: "center", gap: "8px", width: "100%", padding: "7px 10px",
                border: "none", borderRadius: "7px", background: "transparent", cursor: "pointer",
                fontFamily: "inherit", fontSize: "13px", textAlign: "left", color: "var(--danger)",
              }}>
        <Trash2 size={15} strokeWidth={1.7} />
        {working ? "Clearing…" : confirm ? "Click again to clear" : "Clear chat"}
      </button>
      <p style={{ fontSize: "11px", color: "var(--text-soft)", padding: "2px 10px 6px", lineHeight: 1.4 }}>
        Deletes this chat's messages. Saved audits are kept.
      </p>
    </div>
  );
}
