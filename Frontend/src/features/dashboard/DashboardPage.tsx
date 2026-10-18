import { useState } from "react";
import { api } from "@/lib/apiClient";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

interface ChatSession {
  id: string;
  title: string;
  timeAgo: string;
}

const mockSessions: ChatSession[] = [
  { id: "1", title: "Project planning discussion", timeAgo: "2h ago" },
  { id: "2", title: "Flutter app development ideas", timeAgo: "5h ago" },
  { id: "3", title: "Website design suggestions", timeAgo: "1d ago" },
  { id: "4", title: "Learning roadmap", timeAgo: "2d ago" },
  { id: "5", title: "Daily productivity tips", timeAgo: "3d ago" },
];

export function DashboardPage() {
  const [sessions] = useState<ChatSession[]>(mockSessions);
  const [activeSession, setActiveSession] = useState<string>("1");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  async function sendMessage() {
    if (!input.trim() || busy) return;
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: input,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    const text = input;
    setInput("");
    setBusy(true);
    try {
      const resp = await api.c3Copilot({ text, case_id: "CASE-TV" });
      const botMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: (resp as any).reply || "I understand your question. Let me help you with that.",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, botMsg]);
    } catch {
      const botMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "I'm currently offline. Please start the backend server on port 8003 to enable live responses.",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, botMsg]);
    }
    setBusy(false);
  }

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      {/* ── Chat History Sidebar ── */}
      <aside style={{
        width: "240px",
        flexShrink: 0,
        borderRight: "1px solid var(--border-light)",
        padding: "20px 16px",
        display: "flex",
        flexDirection: "column",
        gap: "4px",
        overflowY: "auto",
      }}>
        {/* Sidebar Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "12px" }}>
          <span style={{ fontWeight: 600, fontSize: "13px", color: "var(--text-h)" }}>Chat History</span>
          <button
            style={{
              width: "24px", height: "24px", borderRadius: "6px", border: "1px solid var(--border)",
              background: "transparent", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
              color: "var(--text-muted)", fontSize: "16px", fontFamily: "inherit",
            }}
            onClick={() => { setMessages([]); setActiveSession(""); }}
            title="New chat"
          >+</button>
        </div>

        {/* Session List */}
        {sessions.map((s) => (
          <button
            key={s.id}
            onClick={() => setActiveSession(s.id)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "10px",
              padding: "8px 10px",
              borderRadius: "8px",
              border: "none",
              background: activeSession === s.id ? "var(--sidebar-active)" : "transparent",
              cursor: "pointer",
              width: "100%",
              textAlign: "left",
              fontFamily: "inherit",
              transition: "background 0.15s",
            }}
            onMouseEnter={(e) => { if (activeSession !== s.id) e.currentTarget.style.background = "var(--sidebar-hover)"; }}
            onMouseLeave={(e) => { if (activeSession !== s.id) e.currentTarget.style.background = "transparent"; }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-soft)" strokeWidth="1.5">
              <circle cx="12" cy="12" r="10" />
            </svg>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: "13px", color: "var(--text-h)", fontWeight: activeSession === s.id ? 500 : 400, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {s.title}
              </div>
            </div>
            <span style={{ fontSize: "11px", color: "var(--text-soft)", flexShrink: 0 }}>{s.timeAgo}</span>
          </button>
        ))}
      </aside>

      {/* ── Main Chat Area ── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", position: "relative" }}>
        {/* Messages or Empty State */}
        <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column" }}>
          {messages.length === 0 ? (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "48px 24px" }}>
              <h1 className="heading-serif" style={{ fontSize: "38px", marginBottom: "10px", color: "var(--text-h)" }}>
                What can I help with?
              </h1>
              <p style={{ color: "var(--text-muted)", fontSize: "15px" }}>
                Ask me anything, get ideas, or solve problems.
              </p>
            </div>
          ) : (
            <div style={{ maxWidth: "680px", width: "100%", margin: "0 auto", padding: "32px 24px", display: "flex", flexDirection: "column", gap: "20px" }}>
              {messages.map((m) => (
                <div key={m.id} style={{ display: "flex", flexDirection: "column", alignItems: m.role === "user" ? "flex-end" : "flex-start" }}>
                  <div style={{
                    maxWidth: "85%",
                    padding: "12px 16px",
                    borderRadius: m.role === "user" ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
                    background: m.role === "user" ? "var(--text-h)" : "var(--surface)",
                    color: m.role === "user" ? "#f5f0ea" : "var(--text)",
                    fontSize: "14px",
                    lineHeight: "1.6",
                    border: m.role === "assistant" ? "1px solid var(--border-light)" : "none",
                  }}>
                    {m.content}
                  </div>
                </div>
              ))}
              {busy && (
                <div style={{ display: "flex", alignItems: "flex-start" }}>
                  <div style={{ padding: "12px 16px", borderRadius: "16px 16px 16px 4px", background: "var(--surface)", border: "1px solid var(--border-light)", fontSize: "14px", color: "var(--text-muted)" }}>
                    <span className="thinking-dots">Thinking</span>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Message Input ── */}
        <div style={{ padding: "16px 24px 24px", maxWidth: "680px", width: "100%", margin: "0 auto" }}>
          <div style={{
            background: "var(--input-bg)",
            borderRadius: "var(--radius-xl)",
            padding: "12px 16px",
            display: "flex",
            flexDirection: "column",
            gap: "8px",
          }}>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
              placeholder="Message..."
              style={{
                border: "none",
                outline: "none",
                background: "transparent",
                fontSize: "14px",
                color: "var(--text-h)",
                fontFamily: "inherit",
                width: "100%",
              }}
            />
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ display: "flex", gap: "12px" }}>
                {/* Attachment icons */}
                <button style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-soft)", padding: "2px" }} title="Attach file">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                  </svg>
                </button>
                <button style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-soft)", padding: "2px" }} title="Add image">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                    <circle cx="8.5" cy="8.5" r="1.5" />
                    <polyline points="21 15 16 10 5 21" />
                  </svg>
                </button>
                <button style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-soft)", padding: "2px" }} title="Tools">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
                  </svg>
                </button>
              </div>
              {/* Send button */}
              <button
                onClick={sendMessage}
                disabled={!input.trim() || busy}
                style={{
                  width: "32px",
                  height: "32px",
                  borderRadius: "50%",
                  border: "none",
                  background: input.trim() ? "var(--text-h)" : "var(--border)",
                  cursor: input.trim() ? "pointer" : "default",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  transition: "background 0.2s",
                }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={input.trim() ? "#f5f0ea" : "var(--text-soft)"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="22" y1="2" x2="11" y2="13" />
                  <polygon points="22 2 15 22 11 13 2 9 22 2" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
