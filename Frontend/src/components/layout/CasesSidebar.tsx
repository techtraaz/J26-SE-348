import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Ellipsis, PanelLeft, Pencil, Plus, Search, Trash2, UserRound } from "lucide-react";
import { chat } from "@/lib/apiClient";
import { dateGroup, refreshCaseList, useCaseList, type CaseEntry } from "@/lib/caseList";
import { env } from "@/config/env";
import { useUI } from "@/store/ui";
import { IconButton } from "@/components/ui/IconButton";
import { VERDICT } from "@/lib/verdict";
import { BrandImage } from "@/components/layout/BrandArt";
import { BRAND } from "@/components/layout/brand";
import type { Tone } from "@/types/audit";

// The Chat page's sidebar, below the navy top bar: hide button and "New case" on
// top, the cases (one chat each) grouped by date, the account at the bottom, the
// crest as a faint watermark. Collapses to a narrow rail (Ctrl+B).

const SEARCH_FROM = 8; // the filter box appears once the list is this long

function timeAgo(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  if (mins < 1440) return `${Math.round(mins / 60)}h`;
  return `${Math.round(mins / 1440)}d`;
}

/** The second line of a case: its verdict when audited, else what it holds. */
function caseLine(e: CaseEntry): { tone: Tone | null; text: string } {
  const s = e.summary;
  if (!s) return { tone: null, text: e.staged ? `${e.staged} document(s) ready · not audited` : "not audited yet" };
  const v = s.verdict ? VERDICT[s.verdict] : null;
  if (!v) return { tone: null, text: `v${s.version} · ${s.findings} finding(s)` }; // saved before the verdict existed
  return { tone: v.tone, text: [v.label, s.score ?? null, `v${s.version}`].filter((x) => x !== null).join(" · ") };
}

export function CasesSidebar() {
  const qc = useQueryClient();
  const { selectedCase, setCase, generalSessionId, sidebarOpen: open, toggleSidebar } = useUI();
  const { entries, error, blank, startNewCase } = useCaseList();
  const [query, setQuery] = useState("");

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const shown = q ? entries.filter((e) => `${e.title} ${e.case_id}`.toLowerCase().includes(q)) : entries;
    const out = new Map<string, CaseEntry[]>();
    for (const e of shown) out.set(dateGroup(e.at), [...(out.get(dateGroup(e.at)) ?? []), e]);
    return [...out];
  }, [entries, query]);

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

  async function rename(caseId: string, title: string) {
    await chat.rename(caseId, title, caseId);
    await refreshCaseList(qc);
  }

  return (
    <aside aria-label="Cases" className="slaf-chrome slaf-sidebar" style={{
      width: open ? "288px" : "60px", flexShrink: 0, height: "100%",
      display: "flex", flexDirection: "column", overflow: open ? "hidden" : "visible",
      transition: "width 0.2s ease", position: "relative",
    }}>
      <BrandImage src={BRAND.crest} alt="" className="slaf-sidebar-crest" />

      {/* ── Hide / show and New case (opens a blank case, listed once it holds something) ── */}
      <div style={{ padding: "16px 12px 8px", display: "flex", alignItems: "center", gap: "6px",
                    flexDirection: open ? "row" : "column", position: "relative" }}>
        {open ? (
          <button type="button" className={blank ? "side-row side-row-active" : "side-row"}
                  aria-current={blank ? "page" : undefined} onClick={startNewCase} style={rowStyle(blank)}>
            <span style={{
              width: "30px", height: "30px", borderRadius: "50%", flexShrink: 0,
              background: "var(--surface-muted)", border: "1px solid var(--border-strong)",
              display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-h)",
            }}>
              <Plus size={16} strokeWidth={2} />
            </span>
            <span style={{ fontSize: "14.5px", color: "var(--text-h)", fontWeight: 600 }}>New case</span>
          </button>
        ) : (
          <IconButton tip="New case" tipSide="right" onClick={startNewCase}>
            <Plus size={18} strokeWidth={1.6} />
          </IconButton>
        )}
        <span style={{ order: open ? 1 : -1 }}>
          <IconButton tip={open ? "Hide sidebar" : "Show sidebar"} shortcut="Ctrl+B"
                      tipSide={open ? "bottom-end" : "right"} onClick={toggleSidebar}>
            <PanelLeft size={18} strokeWidth={1.6} />
          </IconButton>
        </span>
      </div>

      {/* ── Cases ── */}
      {open ? (
        <div className="thin-scroll" style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "4px 12px 12px",
                                              position: "relative" }}>
          <SessionButton active={selectedCase === null} onClick={() => setCase(null)} sessionId={generalSessionId}
                         title="General questions" line={{ tone: null, text: "rules, standards, what-ifs" }} />
          {entries.length >= SEARCH_FROM && (
            <label className="side-search">
              <Search size={14} strokeWidth={1.8} aria-hidden />
              <input type="search" aria-label="Search cases" placeholder="Search cases" value={query}
                     onChange={(e) => setQuery(e.target.value)} />
            </label>
          )}
          {error && (
            <p style={{ fontSize: "12px", color: "var(--danger)", margin: "6px 10px" }}>
              Cases unavailable: {error.message}
            </p>
          )}
          {groups.map(([group, items]) => (
            <section key={group} aria-label={group}>
              <h3 className="side-group">{group}</h3>
              {items.map((e) => (
                <SessionButton key={e.case_id} active={selectedCase === e.case_id} onClick={() => setCase(e.case_id)}
                               sessionId={e.case_id} title={e.title} hint={e.case_id} line={caseLine(e)}
                               right={e.at ? timeAgo(e.at) : ""}
                               onRename={(t) => rename(e.case_id, t)} />
              ))}
            </section>
          ))}
          {query && groups.length === 0 && (
            <p style={{ fontSize: "12px", color: "var(--text-soft)", margin: "10px" }}>No case matches “{query}”.</p>
          )}
        </div>
      ) : (
        <div style={{ flex: 1 }} />
      )}

      {/* ── Account ── */}
      <div style={{ borderTop: "1px solid var(--border-light)", padding: "12px 12px 14px", position: "relative",
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

function SessionButton({ active, onClick, sessionId, title, hint, line, right, onRename }: {
  active: boolean; onClick: () => void; sessionId: string; title: string; hint?: string;
  line: { tone: Tone | null; text: string }; right?: string; onRename?: (title: string) => Promise<void>;
}) {
  const [menu, setMenu] = useState(false);
  const [editing, setEditing] = useState(false);
  return (
    <div className={`side-item${menu ? " side-item-menu" : ""}${active ? " side-item-active" : ""}`}
         style={{ position: "relative" }}>
      {editing && onRename ? (
        <RenameBox title={title} onDone={async (t) => {
          setEditing(false);
          if (t !== null && t !== title) await onRename(t).catch(() => undefined);
        }} />
      ) : (
        <button type="button" className={active ? "side-row side-row-active" : "side-row"} onClick={onClick}
                title={hint ? `${title}\n${hint}` : title} aria-current={active ? "page" : undefined}
                style={{ ...rowStyle(active), paddingRight: "36px" }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: "13px", color: "var(--text-h)", fontWeight: active ? 500 : 400, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {title}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "11px", color: "var(--text-soft)", minWidth: 0 }}>
              {line.tone && <span className={`tone-dot tone-${line.tone}`} aria-hidden />}
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{line.text}</span>
            </div>
          </div>
          {right && <span className="side-time" style={{ fontSize: "11px", color: "var(--text-soft)", flexShrink: 0 }}>{right}</span>}
        </button>
      )}
      {!editing && (
        <button type="button" className="side-more" aria-label={`Options for ${title}`} aria-haspopup="menu"
                aria-expanded={menu} onClick={() => setMenu(!menu)}>
          <Ellipsis size={16} strokeWidth={1.8} />
        </button>
      )}
      {menu && <ChatMenu sessionId={sessionId} title={title} onClose={() => setMenu(false)}
                         onRename={onRename ? () => { setMenu(false); setEditing(true); } : undefined} />}
    </div>
  );
}

/** Inline title editor: Enter or leaving saves, Escape cancels; empty puts the automatic name back. */
function RenameBox({ title, onDone }: { title: string; onDone: (title: string | null) => void }) {
  const [value, setValue] = useState(title);
  const done = useRef(false);
  const finish = (t: string | null) => {
    if (done.current) return;
    done.current = true;
    onDone(t === null ? null : t.trim());
  };
  return (
    <input className="side-rename" aria-label="Case name" autoFocus value={value} maxLength={80}
           placeholder="Leave empty for the automatic name"
           onFocus={(e) => e.currentTarget.select()}
           onChange={(e) => setValue(e.target.value)}
           onKeyDown={(e) => {
             if (e.key === "Enter") finish(value);
             if (e.key === "Escape") finish(null);
           }}
           onBlur={() => finish(value)} />
  );
}

/** The "..." menu of one chat. Clearing asks once more, since it cannot be undone. */
function ChatMenu({ sessionId, title, onClose, onRename }: {
  sessionId: string; title: string; onClose: () => void; onRename?: () => void;
}) {
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
    await Promise.all([qc.invalidateQueries({ queryKey: ["chat", sessionId] }), refreshCaseList(qc)]);
    setWorking(false);
    onClose();
  }

  return (
    <div ref={ref} role="menu" aria-label={`Options for ${title}`} style={{
      position: "absolute", top: "calc(100% - 4px)", right: "6px", zIndex: 30, minWidth: "190px",
      padding: "4px", borderRadius: "10px", background: "var(--surface)",
      border: "1px solid var(--border-strong)", boxShadow: "var(--shadow-md)",
    }}>
      {onRename && (
        <button type="button" role="menuitem" className="menu-item" onClick={onRename} style={menuItem}>
          <Pencil size={15} strokeWidth={1.7} />
          Rename
        </button>
      )}
      <button type="button" role="menuitem" className="menu-item menu-item-danger" disabled={working}
              onClick={() => (confirm ? void clear() : setConfirm(true))}
              style={{ ...menuItem, color: "var(--danger)" }}>
        <Trash2 size={15} strokeWidth={1.7} />
        {working ? "Clearing…" : confirm ? "Click again to clear" : "Clear chat"}
      </button>
      <p style={{ fontSize: "11px", color: "var(--text-soft)", padding: "2px 10px 6px", lineHeight: 1.4 }}>
        Deletes this chat's messages and its name. Saved audits are kept.
      </p>
    </div>
  );
}

const menuItem: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: "8px", width: "100%", padding: "7px 10px",
  border: "none", borderRadius: "7px", background: "transparent", cursor: "pointer",
  fontFamily: "inherit", fontSize: "13px", textAlign: "left", color: "var(--text-h)",
};
