import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { c3 } from "@/lib/apiClient";
import { auditSummary } from "@/lib/documents";
import { useUI } from "@/store/ui";
import { routes } from "@/config/routes";

// The case being prepared for audit, beside the document library. Documents
// enter a case as verified records from Component-01, never as uploads here.
export function CasePanel() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { selectedCase, setCase, newCase, draftCases, staged, unstage, clearStaged } = useUI();
  const cases = useQuery({ queryKey: ["c3-cases"], queryFn: c3.cases, retry: false });
  const [notice, setNotice] = useState<{ text: string; error?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  const audited = new Set((cases.data ?? []).map((c) => c.case_id));
  const caseOptions = [...draftCases.filter((id) => !audited.has(id)), ...audited];
  const docs = selectedCase ? staged[selectedCase] ?? [] : [];

  async function audit() {
    if (!selectedCase || !docs.length) return;
    setBusy(true);
    setNotice(null);
    try {
      // The case's chat id is its case id; C3 writes the result into that chat.
      const result = audited.has(selectedCase)
        ? await c3.appendEvidence(selectedCase, docs, selectedCase)
        : await c3.run({ case_id: selectedCase, docs }, selectedCase);
      clearStaged(selectedCase);
      await Promise.all([qc.invalidateQueries({ queryKey: ["c3-cases"] }),
                         qc.invalidateQueries({ queryKey: ["chat", selectedCase] })]);
      setNotice({ text: auditSummary(result) });
    } catch (e) {
      setNotice({ text: e instanceof Error ? e.message : "Audit failed.", error: true });
    }
    setBusy(false);
  }

  return (
    <section aria-label="Case" style={{ padding: "24px 20px" }}>
      <h2 className="heading-serif" style={{ fontSize: "26px", marginBottom: "4px" }}>Case</h2>
      <p style={{ color: "var(--text-muted)", fontSize: "13px", marginBottom: "16px" }}>
        Documents audited together.
      </p>

      <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "20px" }}>
        <select aria-label="Case" value={selectedCase ?? ""} onChange={(e) => setCase(e.target.value || null)}
                style={{ ...selectStyle, flex: 1, minWidth: 0 }}>
          <option value="">Choose a case…</option>
          {caseOptions.map((id) => <option key={id} value={id}>{id}{audited.has(id) ? "" : " (new)"}</option>)}
        </select>
        <button onClick={() => newCase()} style={pillButton}>New case</button>
      </div>

      {notice && (
        <p style={{
          whiteSpace: "pre-wrap", fontSize: "13px", marginBottom: "20px", padding: "10px 14px",
          borderRadius: "var(--radius)", border: `1px solid ${notice.error ? "var(--danger)" : "var(--border-light)"}`,
          color: notice.error ? "var(--danger)" : "var(--text)", background: "var(--surface)",
        }}>{notice.text}</p>
      )}

      {selectedCase && (
        <div>
          <h3 style={{ fontWeight: 600, fontSize: "15px", color: "var(--text-h)", marginBottom: "8px" }}>Documents</h3>
          {docs.length === 0 && (
            <p style={{ fontSize: "13px", color: "var(--text-muted)" }}>
              No documents in this case yet. Verified documents from the library will be added here.
            </p>
          )}
          {docs.map((d) => (
            <Row key={d.doc_id} title={d.doc_id}
                 meta={`${d.doc_type.replace(/_/g, " ")} · ${d.period_year} · ${Object.keys(d.fields).length} field(s)`
                       + (d.parent_doc_id ? ` · supports ${d.parent_doc_id}` : "")}
                 onRemove={() => unstage(selectedCase, d.doc_id)} />
          ))}
          <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", marginTop: "16px" }}>
            {docs.length > 0 && (
              <button onClick={audit} disabled={busy} style={{ ...pillButton, background: "var(--text-h)", color: "var(--bg)", border: "none" }}>
                {busy ? "Auditing…" : audited.has(selectedCase) ? `Add ${docs.length} and re-audit` : `Audit ${docs.length} document(s)`}
              </button>
            )}
            {(docs.length > 0 || audited.has(selectedCase)) && (
              <button onClick={() => navigate(routes.dashboard)} style={pillButton}>Open chat</button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

const selectStyle: React.CSSProperties = {
  padding: "6px 10px", borderRadius: "var(--radius)", border: "1px solid var(--border)",
  background: "var(--surface)", color: "var(--text-h)", fontSize: "13px", fontFamily: "inherit",
};

const pillButton: React.CSSProperties = {
  padding: "8px 18px", borderRadius: "var(--radius-pill)", border: "1px solid var(--border)",
  background: "var(--surface)", color: "var(--text-h)", fontSize: "13px", fontWeight: 500,
  cursor: "pointer", fontFamily: "inherit", whiteSpace: "nowrap",
};

function Row({ title, meta, onRemove }: { title: string; meta: string; onRemove: () => void }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: "10px", padding: "10px 0", borderBottom: "1px solid var(--border-light)" }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="id" style={{ fontWeight: 500, fontSize: "13px", color: "var(--text-h)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</div>
        <div style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "2px" }}>{meta}</div>
      </div>
      <button onClick={onRemove} title="Remove" aria-label={`Remove ${title}`}
              style={{ flexShrink: 0, background: "none", border: "none", cursor: "pointer", color: "var(--text-soft)", padding: "2px" }}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="3 6 5 6 21 6" />
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
        </svg>
      </button>
    </div>
  );
}
