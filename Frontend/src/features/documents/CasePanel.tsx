import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { c3 } from "@/lib/apiClient";
import { auditSummary } from "@/lib/documents";
import { refreshCaseList, useCaseList } from "@/lib/caseList";
import { useUI } from "@/store/ui";
import { routes } from "@/config/routes";
import { VerifiedDocumentPicker } from "./VerifiedDocumentPicker";

// The case being prepared for audit, beside the document library. Documents
// enter a case as verified records from Component-01 (picked, never uploaded).
export function CasePanel() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { selectedCase, setCase, newCase, staged, unstage, clearStaged, setParent } = useUI();
  const { entries, blank, startNewCase } = useCaseList();
  const cases = useQuery({ queryKey: ["c3-cases"], queryFn: c3.cases, retry: false });
  const [notice, setNotice] = useState<{ text: string; error?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [typedMateriality, setTypedMateriality] = useState<Record<string, string>>({});
  // The same picker as the case's chat: both read and write the case's staged documents.
  const [pickingFor, setPickingFor] = useState<string | null>(null);

  const audited = new Set((cases.data ?? []).map((c) => c.case_id));
  const docs = selectedCase ? staged[selectedCase] ?? [] : [];
  const savedMateriality = cases.data?.find((c) => c.case_id === selectedCase)?.materiality ?? null;
  // What the auditor typed for this case, else the case's saved materiality.
  const materiality = (selectedCase && typedMateriality[selectedCase])
    ?? (savedMateriality != null ? String(savedMateriality) : "");
  const setMateriality = (value: string) =>
    selectedCase && setTypedMateriality((m) => ({ ...m, [selectedCase]: value }));

  async function audit() {
    if (!selectedCase || !docs.length) return;
    const typed = materiality.replace(/[,\s]/g, "").replace(/^(rs|lkr)\.?/i, "");
    const amount = typed ? Number(typed) : undefined;
    if (amount !== undefined && !(amount >= 0)) {
      setNotice({ text: "Materiality must be an amount, e.g. 50000, or left empty.", error: true });
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      // The case's chat id is its case id; C3 writes the result into that chat.
      const result = audited.has(selectedCase)
        ? await c3.appendEvidence(selectedCase, docs, selectedCase, amount)
        : await c3.run({ case_id: selectedCase, docs, ...(amount !== undefined ? { materiality: amount } : {}) },
                       selectedCase);
      clearStaged(selectedCase);
      await Promise.all([refreshCaseList(qc), qc.invalidateQueries({ queryKey: ["chat", selectedCase] })]);
      setNotice({ text: auditSummary(result) });
    } catch (e) {
      setNotice({ text: e instanceof Error ? e.message : "Audit failed.", error: true });
    }
    setBusy(false);
  }

  return (
    <section aria-label="Case" style={{ padding: "44px 24px 24px" }}>
      <h2 className="heading-serif" style={{ fontSize: "26px", marginBottom: "4px" }}>Case</h2>
      <p style={{ color: "var(--text-muted)", fontSize: "13px", marginBottom: "16px" }}>
        Documents audited together.
      </p>

      <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "24px" }}>
        <select aria-label="Case" value={selectedCase ?? ""} onChange={(e) => setCase(e.target.value || null)}
                style={{ ...selectStyle, flex: 1, minWidth: 0 }}>
          <option value="">Choose a case…</option>
          {blank && selectedCase && <option value={selectedCase}>New case</option>}
          {entries.map((e) => (
            <option key={e.case_id} value={e.case_id}>{e.title}{e.summary ? "" : " (not audited)"}</option>
          ))}
        </select>
        <button onClick={startNewCase} style={pillButton}>New case</button>
      </div>

      {selectedCase && (
        <label style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "20px", fontSize: "13px",
                        color: "var(--text-muted)" }}>
          Materiality (Rs)
          <input aria-label="Materiality" value={materiality} inputMode="decimal" placeholder="optional, e.g. 50,000"
                 onChange={(e) => setMateriality(e.target.value)}
                 style={{ ...selectStyle, flex: 1, minWidth: 0 }} />
        </label>
      )}
      {selectedCase && materiality.trim() !== "" && (
        <p style={{ fontSize: "12px", color: "var(--text-soft)", margin: "-12px 0 20px" }}>
          Differences below this stay as findings, at low severity. Fraud patterns are never softened.
        </p>
      )}

      {notice && (
        <p style={{
          whiteSpace: "pre-wrap", fontSize: "13px", marginBottom: "20px", padding: "10px 14px",
          borderRadius: "var(--radius)", border: `1px solid ${notice.error ? "var(--danger)" : "var(--border-light)"}`,
          color: notice.error ? "var(--danger)" : "var(--text)", background: "var(--surface)",
        }}>{notice.text}</p>
      )}

      <div style={{ borderTop: "1px solid var(--border-light)", paddingTop: "20px" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px", marginBottom: "8px" }}>
          <h3 style={{ fontWeight: 600, fontSize: "15px", color: "var(--text-h)" }}>Documents</h3>
          <button onClick={() => setPickingFor(selectedCase ?? newCase())} style={{ ...pillButton, height: "30px", padding: "0 12px", fontSize: "12px" }}
                  title="Pick verified documents from the library">
            + Add verified
          </button>
        </div>
        {!selectedCase && (
          <p style={{ fontSize: "13px", color: "var(--text-muted)" }}>
            Choose a case, or add verified documents to start a new one.
          </p>
        )}
      </div>
      {pickingFor && <VerifiedDocumentPicker caseId={pickingFor} onClose={() => setPickingFor(null)} />}

      {selectedCase && (
        <div style={{ paddingTop: "4px" }}>
          {docs.length === 0 && (
            <p style={{ fontSize: "13px", color: "var(--text-muted)" }}>
              No documents in this case yet.
            </p>
          )}
          {docs.map((d) => (
            <Row key={d.doc_id} title={d.name || d.doc_id}
                 meta={`${d.doc_type.replace(/_/g, " ")} · ${d.period_year} · ${Object.keys(d.fields).length} field(s)`}
                 onRemove={() => unstage(selectedCase, d.doc_id)}>
              {docs.length > 1 && (
                // A supporting document (PO, GRN, receipt) links to the one it supports, so
                // cross-document rules such as CHK-003 (amount matches) can run.
                <label style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "6px",
                                fontSize: "12px", color: "var(--text-muted)" }}>
                  Supports
                  <select aria-label={`${d.name || d.doc_id} supports`} value={d.parent_doc_id ?? ""}
                          onChange={(e) => setParent(selectedCase, d.doc_id, e.target.value || null)}
                          style={{ ...selectStyle, height: "28px", fontSize: "12px", flex: 1, minWidth: 0 }}>
                    <option value="">nothing (stands alone)</option>
                    {docs.filter((o) => o.doc_id !== d.doc_id).map((o) => (
                      <option key={o.doc_id} value={o.doc_id}>{o.name || o.doc_id}</option>
                    ))}
                  </select>
                </label>
              )}
            </Row>
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
  height: "36px", padding: "0 10px", borderRadius: "var(--radius)", border: "1px solid var(--border)",
  background: "var(--surface)", color: "var(--text-h)", fontSize: "13px", fontFamily: "inherit",
};

const pillButton: React.CSSProperties = {
  height: "36px", padding: "0 18px", borderRadius: "var(--radius-pill)", border: "1px solid var(--border)",
  background: "var(--surface)", color: "var(--text-h)", fontSize: "13px", fontWeight: 500,
  cursor: "pointer", fontFamily: "inherit", whiteSpace: "nowrap",
};

function Row({ title, meta, onRemove, children }:
  { title: string; meta: string; onRemove: () => void; children?: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: "10px", padding: "10px 0", borderBottom: "1px solid var(--border-light)" }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="id" style={{ fontWeight: 500, fontSize: "13px", color: "var(--text-h)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</div>
        <div style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "2px" }}>{meta}</div>
        {children}
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
