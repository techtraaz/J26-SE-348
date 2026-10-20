import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { c3, chat } from "@/lib/apiClient";
import { VerifiedDocumentPicker } from "@/features/documents/VerifiedDocumentPicker";
import { useUI } from "@/store/ui";
import { FindingCard } from "@/components/audit/FindingCard";
import { Plus, Sparkles } from "lucide-react";
import { IconButton } from "@/components/ui/IconButton";
import type { ChatMessage, Finding } from "@/types/audit";

const STARTERS = [
  "Summarise this case",
  "Which rules apply to invoices?",
  "Which cases have high severity findings?",
  "I paid Rs 150,000 cash for a laptop but booked it on credit, is that ok?",
];
const SHOWN_FINDINGS = 6;

// Shown only until the server answers (pending) or because sending failed (not saved).
type LocalMessage = { key: string; role: "user" | "error"; text: string; attached?: number };

/** The reply text lists findings as "- RULE ..." lines; drop those when cards show them. */
function replyText(content: string, findings: Finding[]): string {
  if (!findings.length) return content;
  const ids = new Set(findings.map((f) => f.rule_id));
  return content.split("\n")
    .filter((line) => !(line.startsWith("- ") && ids.has(line.slice(2).split(" ")[0])))
    .filter((line) => !/^\.{0,3}and \d+ more\.$/.test(line.trim()))
    .join("\n").trim();
}

export function DashboardPage() {
  const qc = useQueryClient();
  const { selectedCase, newCase, generalSessionId, staged, clearStaged } = useUI();
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // The message box grows with its text, up to a limit, then scrolls.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [input]);
  const [busy, setBusy] = useState(false);
  // Case documents come only from verified Component-01 documents (D16), picked here.
  const [pickingFor, setPickingFor] = useState<string | null>(null);
  const [local, setLocal] = useState<Record<string, LocalMessage[]>>({});
  const endRef = useRef<HTMLDivElement>(null);

  const sessionId = selectedCase ?? generalSessionId; // a case's chat id is its case id
  const history = useQuery({ queryKey: ["chat", sessionId], queryFn: () => chat.messages(sessionId), retry: false });
  const saved = history.data ?? [];
  const pending = local[sessionId] ?? [];
  const attached = selectedCase ? staged[selectedCase] ?? [] : [];

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); },
            [saved.length, pending.length, busy]);

  const addLocal = (m: LocalMessage) => setLocal((s) => ({ ...s, [sessionId]: [...(s[sessionId] ?? []), m] }));
  const dropLocal = (key: string) =>
    setLocal((s) => ({ ...s, [sessionId]: (s[sessionId] ?? []).filter((m) => m.key !== key) }));

  async function send(textArg?: string) {
    const docs = attached;
    const text = (textArg ?? input).trim() || (docs.length ? "Audit these documents" : "");
    if (!text || busy) return;
    const key = crypto.randomUUID();
    addLocal({ key, role: "user", text, attached: docs.length || undefined });
    setInput("");
    setBusy(true);
    try {
      const r = await c3.copilot({ text, case_id: selectedCase, session_id: sessionId, docs });
      await qc.invalidateQueries({ queryKey: ["chat", sessionId] });
      dropLocal(key);
      if (docs.length && selectedCase && r.data?.version) clearStaged(selectedCase);
      if (r.group === "fresh_audit" || r.group === "evidence_append") {
        await qc.invalidateQueries({ queryKey: ["c3-cases"] });
      }
    } catch (e) {
      addLocal({ key: crypto.randomUUID(), role: "error",
                 text: e instanceof Error ? e.message : "Request failed." });
    }
    setBusy(false);
  }

  const empty = saved.length === 0 && pending.length === 0;
  const last = saved[saved.length - 1];

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      {/* ── Conversation ── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", position: "relative", minWidth: 0 }}>
        <div className="thin-scroll" style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column" }}>
          {empty ? (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "48px 24px" }}>
              <h1 className="heading-serif" style={{ fontSize: "38px", marginBottom: "10px", color: "var(--text-h)" }}>
                What can I help with?
              </h1>
              <p style={{ color: "var(--text-muted)", fontSize: "15px", marginBottom: "20px", textAlign: "center" }}>
                {history.isError
                  ? `Chat history unavailable: ${(history.error as Error).message}`
                  : selectedCase
                    ? `Ask about case ${selectedCase}, or add verified documents to audit them.`
                    : "Ask about rules, standards or your cases, or describe a transaction to check it."}
              </p>
              <Chips items={STARTERS} onPick={(t) => send(t)} disabled={busy} />
            </div>
          ) : (
            <div style={{ maxWidth: "720px", width: "100%", margin: "0 auto", padding: "40px 24px 32px", display: "flex", flexDirection: "column", gap: "20px" }}>
              {saved.map((m) => (
                <Message key={m.message_id} m={m} showSuggestions={m === last && !pending.length}
                         busy={busy} onPick={(t) => send(t)} />
              ))}
              {pending.map((m) => (
                <Bubble key={m.key} user={m.role === "user"} error={m.role === "error"}>
                  {m.text}
                  {m.attached ? <div style={{ fontSize: "12px", opacity: 0.75, marginTop: "4px" }}>+ {m.attached} document(s)</div> : null}
                </Bubble>
              ))}
              {busy && (
                <div style={{ display: "flex", alignItems: "flex-start" }}>
                  <div style={{ padding: "12px 16px", borderRadius: "16px 16px 16px 4px", background: "var(--surface)", border: "1px solid var(--border-strong)", fontSize: "14px", color: "var(--text-muted)" }}>
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
          {attached.length > 0 && (
            <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "8px", fontSize: "12px", flexWrap: "wrap" }}>
              <span style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-pill)", padding: "3px 10px", color: "var(--text-h)" }}>
                {attached.length} document(s) attached to {selectedCase}
                <button onClick={() => selectedCase && clearStaged(selectedCase)} title="Remove"
                        style={{ marginLeft: "6px", background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)" }}>×</button>
              </span>
            </div>
          )}
          {/* Clicking anywhere in the box (except its buttons) puts the cursor in the text. */}
          <div
            className="chat-composer"
            onMouseDown={(e) => {
              if (!(e.target as HTMLElement).closest("button, textarea")) {
                e.preventDefault();
                inputRef.current?.focus();
              }
            }}
            style={{
              background: "var(--input-bg)", borderRadius: "var(--radius-xl)", padding: "14px 14px 10px 18px",
              display: "flex", flexDirection: "column", gap: "10px", cursor: "text",
              border: "1px solid var(--border-strong)", boxShadow: "var(--shadow-sm)",
            }}
          >
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder={attached.length ? "Say what to do with the documents, or press Enter to audit them" : "Message..."}
              aria-label="Message"
              style={{
                border: "none", outline: "none", background: "transparent", fontSize: "14px", lineHeight: "22px",
                color: "var(--text-h)", fontFamily: "inherit", width: "100%", resize: "none", padding: 0,
                minHeight: "22px", maxHeight: "200px", overflowY: "auto",
              }}
            />
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px" }}>
              <IconButton tip="Add verified documents" tipSide="top" bordered
                          onClick={() => setPickingFor(selectedCase ?? newCase())}>
                <Plus size={17} strokeWidth={1.7} />
              </IconButton>
              {pickingFor && <VerifiedDocumentPicker caseId={pickingFor} onClose={() => setPickingFor(null)} />}
              <SendButton ready={Boolean(input.trim() || attached.length) && !busy} onClick={() => send()} />
            </div>
          </div>
          <p style={{ textAlign: "center", fontSize: "11px", color: "var(--text-soft)", marginTop: "8px" }}>
            NOMOS can make mistakes. Verify important findings against the evidence.
          </p>
        </div>
      </div>
    </div>
  );
}

function Bubble({ user, error, children }: { user: boolean; error?: boolean; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: user ? "flex-end" : "flex-start" }}>
      <div style={{
        maxWidth: "85%", padding: "12px 16px",
        borderRadius: user ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
        background: user ? "var(--text-h)" : "var(--surface)",
        color: user ? "var(--bg)" : error ? "var(--danger)" : "var(--text)",
        fontSize: "14px", lineHeight: "1.6", whiteSpace: "pre-wrap",
        border: user ? "none" : `1px solid ${error ? "var(--danger)" : "var(--border-strong)"}`,
        boxShadow: user ? "none" : "var(--shadow-sm)",
      }}>{children}</div>
    </div>
  );
}

function Message({ m, showSuggestions, busy, onPick }: {
  m: ChatMessage; showSuggestions: boolean; busy: boolean; onPick: (t: string) => void;
}) {
  const [all, setAll] = useState(false);
  const user = m.role === "user";
  const shown = all ? m.findings : m.findings.slice(0, SHOWN_FINDINGS);
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: user ? "flex-end" : "flex-start", gap: "8px" }}>
      {m.role === "report" || m.role === "system" ? (
        <div style={{
          maxWidth: "85%", padding: "10px 14px", borderRadius: "var(--radius)", fontSize: "13px",
          border: "1px dashed var(--border-strong)", color: "var(--text)", background: "var(--accent-bg)",
        }}>
          <span style={{ fontWeight: 600, color: "var(--text-h)" }}>
            {m.role === "report" ? `Report${m.refs?.version ? ` · v${m.refs.version}` : ""}` : "Notice"} ({m.source.toUpperCase()})
          </span>
          <div style={{ whiteSpace: "pre-wrap", marginTop: "4px" }}>{m.text}</div>
          {typeof m.data.report_url === "string" && (
            <a href={m.data.report_url} target="_blank" rel="noreferrer" style={{ color: "var(--text-h)", fontSize: "12px" }}>Open report</a>
          )}
        </div>
      ) : (
        <Bubble user={user}>
          {user ? m.text : replyText(m.text, m.findings)}
          {m.data.attached_docs ? <div style={{ fontSize: "12px", opacity: 0.75, marginTop: "4px" }}>+ {m.data.attached_docs} document(s)</div> : null}
        </Bubble>
      )}
      {!user && typeof m.data.trace_id === "string" && <ExplainButton runKey={m.data.trace_id} />}
      {m.findings.length > 0 && (
        <div style={{ width: "85%", display: "flex", flexDirection: "column", gap: "6px" }}>
          {shown.map((f) => <FindingCard key={f.finding_id} f={f} />)}
          {m.findings.length > SHOWN_FINDINGS && (
            <button onClick={() => setAll(!all)} style={{
              alignSelf: "flex-start", background: "none", border: "none", cursor: "pointer",
              color: "var(--text-muted)", fontSize: "12px", fontFamily: "inherit", padding: 0,
            }}>{all ? "Show fewer" : `Show all ${m.findings.length} findings`}</button>
          )}
        </div>
      )}
      {m.data.refs_missing ? <span style={{ fontSize: "12px", color: "var(--text-soft)" }}>The audit version this message refers to is no longer available.</span> : null}
      {showSuggestions && !user && m.suggestions.length ? <Chips items={m.suggestions} onPick={onPick} disabled={busy} /> : null}
    </div>
  );
}

/** Opens the Explainability panel on the trace of this reply. */
function ExplainButton({ runKey }: { runKey: string }) {
  const explainRun = useUI((s) => s.explainRun);
  return (
    <button
      type="button"
      className="icon-btn"
      onClick={() => explainRun(runKey)}
      aria-label="Explain this reply"
      data-tip="Show how this reply was reached"
      data-tip-side="right"
      style={{
        display: "inline-flex", alignItems: "center", gap: "6px", height: "28px", padding: "0 10px",
        marginTop: "-2px", borderRadius: "8px", border: "none", background: "transparent",
        color: "var(--text-muted)", cursor: "pointer", fontFamily: "inherit", fontSize: "12.5px", fontWeight: 500,
      }}
    >
      <Sparkles size={14} strokeWidth={1.6} />
      Explain
    </button>
  );
}

function SendButton({ ready, onClick }: { ready: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} disabled={!ready} style={{
      width: "32px", height: "32px", borderRadius: "50%", border: "none",
      background: ready ? "var(--text-h)" : "var(--border)", cursor: ready ? "pointer" : "default",
      display: "flex", alignItems: "center", justifyContent: "center", transition: "background 0.2s",
    }}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={ready ? "var(--bg)" : "var(--text-soft)"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="22" y1="2" x2="11" y2="13" />
        <polygon points="22 2 15 22 11 13 2 9 22 2" />
      </svg>
    </button>
  );
}

function Chips({ items, onPick, disabled }: { items: string[]; onPick: (t: string) => void; disabled: boolean }) {
  return (
    <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", maxWidth: "640px", justifyContent: "inherit" }}>
      {items.map((t) => (
        <button key={t} onClick={() => onPick(t)} disabled={disabled} style={{
          padding: "6px 12px", borderRadius: "var(--radius-pill)", border: "1px solid var(--border-strong)",
          background: "var(--surface)", color: "var(--text-h)", fontSize: "12px", cursor: disabled ? "default" : "pointer",
          fontFamily: "inherit",
        }}>{t}</button>
      ))}
    </div>
  );
}
