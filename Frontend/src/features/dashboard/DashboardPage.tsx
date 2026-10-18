import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { c3 } from "@/lib/apiClient";
import { isJsonFile, readJsonDocuments } from "@/lib/documents";
import { useUI, type ChatMessage } from "@/store/ui";
import { FindingCard } from "@/components/audit/FindingCard";
import type { CaseSummary, Finding } from "@/types/audit";

const STARTERS = [
  "Summarise this case",
  "Which rules apply to invoices?",
  "Which cases have high severity findings?",
  "I paid Rs 150,000 cash for a laptop but booked it on credit, is that ok?",
];
const SHOWN_FINDINGS = 6;

// A case in the sidebar: audited (with its latest summary) or started here and not audited yet.
type SidebarCase = { case_id: string; summary: CaseSummary | null };

function timeAgo(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return `${mins}m ago`;
  if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
  return `${Math.round(mins / 1440)}d ago`;
}

/** The reply text lists findings as "- RULE ..." lines; drop those when cards show them. */
function replyText(content: string, findings?: Finding[]): string {
  if (!findings?.length) return content;
  const ids = new Set(findings.map((f) => f.rule_id));
  return content.split("\n")
    .filter((line) => !(line.startsWith("- ") && ids.has(line.slice(2).split(" ")[0])))
    .filter((line) => !/^…?\.{0,3}and \d+ more\.$/.test(line.trim()))
    .join("\n").trim();
}

export function DashboardPage() {
  const qc = useQueryClient();
  const { selectedCase, setCase, newCase, draftCases, messages, addMessage, staged, stageDocs, clearStaged } = useUI();
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [attachError, setAttachError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const cases = useQuery({ queryKey: ["c3-cases"], queryFn: c3.cases, retry: false });
  const sessionKey = selectedCase ?? "_general";
  const thread = messages[sessionKey] ?? [];
  const attached = selectedCase ? staged[selectedCase] ?? [] : [];

  const sidebar = useMemo((): SidebarCase[] => {
    const audited = cases.data ?? [];
    const known = new Set(audited.map((c) => c.case_id));
    const drafts = draftCases.filter((id) => !known.has(id)).map((id) => ({ case_id: id, summary: null }));
    return [...drafts, ...audited.map((c) => ({ case_id: c.case_id, summary: c }))];
  }, [cases.data, draftCases]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [thread.length, busy]);

  async function send(textArg?: string) {
    const docs = attached;
    const text = (textArg ?? input).trim() || (docs.length ? "Audit these documents" : "");
    if (!text || busy) return;
    addMessage(sessionKey, { id: crypto.randomUUID(), role: "user", content: text,
                             attached: docs.length || undefined });
    setInput("");
    setBusy(true);
    try {
      const r = await c3.copilot({ text, case_id: selectedCase, docs });
      const findings = (r.data?.findings ?? []) as Finding[];
      addMessage(sessionKey, { id: crypto.randomUUID(), role: "assistant", content: r.reply,
                               findings, suggestions: r.suggestions });
      if (docs.length && selectedCase && r.data?.version) clearStaged(selectedCase);
      if (r.group === "fresh_audit" || r.group === "evidence_append") {
        await qc.invalidateQueries({ queryKey: ["c3-cases"] });
      }
    } catch (e) {
      addMessage(sessionKey, { id: crypto.randomUUID(), role: "assistant", error: true,
                               content: e instanceof Error ? e.message : "Request failed." });
    }
    setBusy(false);
  }

  async function attach(files: FileList) {
    setAttachError("");
    const caseId = selectedCase ?? newCase();
    try {
      const docs = [];
      for (const f of Array.from(files)) {
        if (!isJsonFile(f)) throw new Error(`${f.name}: attach JSON documents here; send scans through the Library.`);
        docs.push(...await readJsonDocuments(f));
      }
      stageDocs(caseId, docs);
    } catch (e) {
      setAttachError(e instanceof Error ? e.message : "Could not read the file.");
    }
  }

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      {/* ── Cases (one chat per case) ── */}
      <aside style={{
        width: "240px", flexShrink: 0, borderRight: "1px solid var(--border-light)",
        padding: "20px 16px", display: "flex", flexDirection: "column", gap: "4px", overflowY: "auto",
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "12px" }}>
          <span style={{ fontWeight: 600, fontSize: "13px", color: "var(--text-h)" }}>Cases</span>
          <button
            style={{
              width: "24px", height: "24px", borderRadius: "6px", border: "1px solid var(--border)",
              background: "transparent", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
              color: "var(--text-muted)", fontSize: "16px", fontFamily: "inherit",
            }}
            onClick={() => newCase()}
            title="New case"
          >+</button>
        </div>

        <SessionButton active={selectedCase === null} onClick={() => setCase(null)}
                       title="General questions" meta="rules, standards, what-ifs" />
        {cases.isError && (
          <p style={{ fontSize: "12px", color: "var(--danger)", margin: "6px 4px" }}>
            Cases unavailable: {(cases.error as Error).message}
          </p>
        )}
        {sidebar.map((c) => (
          <SessionButton key={c.case_id} active={selectedCase === c.case_id} onClick={() => setCase(c.case_id)}
                         title={c.case_id} meta={c.summary ? caseMeta(c.summary) : "new · not audited"}
                         right={c.summary ? timeAgo(c.summary.created_at) : ""} />
        ))}
      </aside>

      {/* ── Conversation ── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", position: "relative", minWidth: 0 }}>
        <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column" }}>
          {thread.length === 0 ? (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "48px 24px" }}>
              <h1 className="heading-serif" style={{ fontSize: "38px", marginBottom: "10px", color: "var(--text-h)" }}>
                What can I help with?
              </h1>
              <p style={{ color: "var(--text-muted)", fontSize: "15px", marginBottom: "20px", textAlign: "center" }}>
                {selectedCase
                  ? `Ask about case ${selectedCase}, or attach documents to audit them.`
                  : "Ask about rules, standards or your cases, or describe a transaction to check it."}
              </p>
              <Chips items={STARTERS} onPick={(t) => send(t)} disabled={busy} />
            </div>
          ) : (
            <div style={{ maxWidth: "720px", width: "100%", margin: "0 auto", padding: "32px 24px", display: "flex", flexDirection: "column", gap: "20px" }}>
              {thread.map((m, i) => (
                <Message key={m.id} m={m} last={i === thread.length - 1} busy={busy} onPick={(t) => send(t)} />
              ))}
              {busy && (
                <div style={{ display: "flex", alignItems: "flex-start" }}>
                  <div style={{ padding: "12px 16px", borderRadius: "16px 16px 16px 4px", background: "var(--surface)", border: "1px solid var(--border-light)", fontSize: "14px", color: "var(--text-muted)" }}>
                    <span className="thinking-dots">Thinking</span>
                  </div>
                </div>
              )}
              <div ref={endRef} />
            </div>
          )}
        </div>

        {/* ── Message input ── */}
        <div style={{ padding: "16px 24px 24px", maxWidth: "720px", width: "100%", margin: "0 auto" }}>
          {(attached.length > 0 || attachError) && (
            <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "8px", fontSize: "12px", flexWrap: "wrap" }}>
              {attached.length > 0 && (
                <span style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-pill)", padding: "3px 10px", color: "var(--text-h)" }}>
                  {attached.length} document(s) attached to {selectedCase}
                  <button onClick={() => selectedCase && clearStaged(selectedCase)} title="Remove"
                          style={{ marginLeft: "6px", background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)" }}>×</button>
                </span>
              )}
              {attachError && <span style={{ color: "var(--danger)" }}>{attachError}</span>}
            </div>
          )}
          <div style={{
            background: "var(--input-bg)", borderRadius: "var(--radius-xl)", padding: "12px 16px",
            display: "flex", flexDirection: "column", gap: "8px",
          }}>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder={attached.length ? "Say what to do with the documents, or press Enter to audit them" : "Message..."}
              style={{ border: "none", outline: "none", background: "transparent", fontSize: "14px", color: "var(--text-h)", fontFamily: "inherit", width: "100%" }}
            />
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <button onClick={() => fileRef.current?.click()} title="Attach JSON documents"
                      style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-soft)", padding: "2px" }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                </svg>
              </button>
              <input ref={fileRef} type="file" accept=".json,application/json" multiple style={{ display: "none" }}
                     onChange={(e) => { if (e.target.files) attach(e.target.files); e.target.value = ""; }} />
              {(() => {
                const ready = Boolean(input.trim() || attached.length) && !busy;
                return (
                  <button onClick={() => send()} disabled={!ready} style={{
                    width: "32px", height: "32px", borderRadius: "50%", border: "none",
                    background: ready ? "var(--text-h)" : "var(--border)", cursor: ready ? "pointer" : "default",
                    display: "flex", alignItems: "center", justifyContent: "center", transition: "background 0.2s",
                  }}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={ready ? "#f5f0ea" : "var(--text-soft)"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="22" y1="2" x2="11" y2="13" />
                      <polygon points="22 2 15 22 11 13 2 9 22 2" />
                    </svg>
                  </button>
                );
              })()}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function caseMeta(c: CaseSummary): string {
  if (c.status === "not_auditable") return `v${c.version} · not auditable`;
  return `v${c.version} · ${c.findings} finding(s)${c.high ? `, ${c.high} high` : ""}`;
}

function SessionButton({ active, onClick, title, meta, right }: {
  active: boolean; onClick: () => void; title: string; meta: string; right?: string;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "flex", alignItems: "center", gap: "10px", padding: "8px 10px", borderRadius: "8px",
        border: "none", background: active ? "var(--sidebar-active)" : "transparent", cursor: "pointer",
        width: "100%", textAlign: "left", fontFamily: "inherit", transition: "background 0.15s",
      }}
      onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = "var(--sidebar-hover)"; }}
      onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = "transparent"; }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: "13px", color: "var(--text-h)", fontWeight: active ? 500 : 400, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {title}
        </div>
        <div style={{ fontSize: "11px", color: "var(--text-soft)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{meta}</div>
      </div>
      {right && <span style={{ fontSize: "11px", color: "var(--text-soft)", flexShrink: 0 }}>{right}</span>}
    </button>
  );
}

function Message({ m, last, busy, onPick }: { m: ChatMessage; last: boolean; busy: boolean; onPick: (t: string) => void }) {
  const [all, setAll] = useState(false);
  const user = m.role === "user";
  const findings = m.findings ?? [];
  const shown = all ? findings : findings.slice(0, SHOWN_FINDINGS);
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: user ? "flex-end" : "flex-start", gap: "8px" }}>
      <div style={{
        maxWidth: "85%", padding: "12px 16px",
        borderRadius: user ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
        background: user ? "var(--text-h)" : "var(--surface)",
        color: user ? "#f5f0ea" : m.error ? "var(--danger)" : "var(--text)",
        fontSize: "14px", lineHeight: "1.6", whiteSpace: "pre-wrap",
        border: user ? "none" : `1px solid ${m.error ? "var(--danger)" : "var(--border-light)"}`,
      }}>
        {user ? m.content : replyText(m.content, findings)}
        {m.attached ? <div style={{ fontSize: "12px", opacity: 0.75, marginTop: "4px" }}>+ {m.attached} document(s)</div> : null}
      </div>
      {findings.length > 0 && (
        <div style={{ width: "85%", display: "flex", flexDirection: "column", gap: "6px" }}>
          {shown.map((f) => <FindingCard key={f.finding_id} f={f} />)}
          {findings.length > SHOWN_FINDINGS && (
            <button onClick={() => setAll(!all)} style={{
              alignSelf: "flex-start", background: "none", border: "none", cursor: "pointer",
              color: "var(--text-muted)", fontSize: "12px", fontFamily: "inherit", padding: 0,
            }}>{all ? "Show fewer" : `Show all ${findings.length} findings`}</button>
          )}
        </div>
      )}
      {last && !user && m.suggestions?.length ? <Chips items={m.suggestions} onPick={onPick} disabled={busy} /> : null}
    </div>
  );
}

function Chips({ items, onPick, disabled }: { items: string[]; onPick: (t: string) => void; disabled: boolean }) {
  return (
    <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", maxWidth: "640px", justifyContent: "inherit" }}>
      {items.map((t) => (
        <button key={t} onClick={() => onPick(t)} disabled={disabled} style={{
          padding: "6px 12px", borderRadius: "var(--radius-pill)", border: "1px solid var(--border)",
          background: "var(--surface)", color: "var(--text-h)", fontSize: "12px", cursor: disabled ? "default" : "pointer",
          fontFamily: "inherit",
        }}>{t}</button>
      ))}
    </div>
  );
}
