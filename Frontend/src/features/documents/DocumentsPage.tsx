import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { c1, c3 } from "@/lib/apiClient";
import { auditSummary, isJsonFile, isScan, readJsonDocuments } from "@/lib/documents";
import { useUI } from "@/store/ui";
import { routes } from "@/config/routes";
import type { C1Record, DocumentPreview } from "@/types/review";
import { ReviewPanel, type ReviewResult } from "@/features/documents/ReviewPanel";

// A scanned file on its way through Component-01, then reviewed before it joins the case.
interface Scan {
  key: string;
  name: string;
  state: "uploading" | "extracting" | "reading" | "review" | "error";
  message?: string;
  record?: C1Record; // C1's verified record when it has one, else its extraction
  preview?: DocumentPreview;
}

const SCAN_STATE: Record<Scan["state"], string> = {
  uploading: "Uploading to Component 01…", extracting: "Component 01 is reading the document…",
  reading: "Matching lines to fields…", review: "", error: "",
};
const POLL_MS = 2000;
const POLL_LIMIT = 90; // ~3 minutes
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function DocumentsPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { selectedCase, setCase, newCase, draftCases, staged, stageDocs, unstage, clearStaged } = useUI();
  const cases = useQuery({ queryKey: ["c3-cases"], queryFn: c3.cases, retry: false });
  const [scans, setScans] = useState<Scan[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [notice, setNotice] = useState<{ text: string; error?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const audited = new Set((cases.data ?? []).map((c) => c.case_id));
  const caseOptions = [...draftCases.filter((id) => !audited.has(id)), ...audited];
  const docs = selectedCase ? staged[selectedCase] ?? [] : [];

  const updateScan = (key: string, patch: Partial<Scan>) =>
    setScans((prev) => prev.map((s) => (s.key === key ? { ...s, ...patch } : s)));

  // C3 reads the lines into fields; the reviewer checks them in the panel.
  const readScan = useCallback(async (key: string, record: C1Record, docType?: string) => {
    const { selectedCase: current, newCase: create } = useUI.getState();
    const caseId = current ?? create();
    try {
      const [preview] = await c3.previewC1(caseId, [{ ...record, ...(docType ? { doc_type: docType } : {}) }]);
      updateScan(key, { state: "review", preview });
    } catch (e) {
      updateScan(key, { state: "error", message: e instanceof Error ? e.message : "Could not read the document." });
    }
  }, []);

  const extract = useCallback(async (key: string, file: File) => {
    try {
      const { id } = await c1.upload(file);
      updateScan(key, { state: "extracting" });
      for (let i = 0; i < POLL_LIMIT; i++) {
        const doc = await c1.status(id);
        const state = doc.latest_run?.status;
        if (state === "succeeded") {
          const verified = await c1.verified(id);
          const record: C1Record = verified ? { verified } : { extraction: await c1.extraction(id) };
          updateScan(key, { state: "reading", record });
          await readScan(key, record);
          return;
        }
        if (state === "failed") throw new Error(doc.error_message || "Extraction failed in Component 01.");
        await sleep(POLL_MS);
      }
      throw new Error("Extraction is taking too long; try again later.");
    } catch (e) {
      updateScan(key, { state: "error", message: e instanceof Error ? e.message : "Upload failed." });
    }
  }, [readScan]);

  const handleFiles = useCallback(async (fileList: FileList) => {
    setNotice(null);
    const caseId = selectedCase ?? newCase();
    const problems: string[] = [];
    for (const f of Array.from(fileList)) {
      if (isJsonFile(f)) {
        try {
          stageDocs(caseId, await readJsonDocuments(f));
        } catch (e) {
          problems.push(e instanceof Error ? e.message : `${f.name}: unreadable`);
        }
      } else if (isScan(f) && c1.enabled()) {
        const key = crypto.randomUUID();
        setScans((prev) => [...prev, { key, name: f.name, state: "uploading" }]);
        extract(key, f);
      } else if (isScan(f)) {
        problems.push(`${f.name}: scanned documents need Component 01 (set VITE_C1_BASE). Upload JSON documents for now.`);
      } else {
        problems.push(`${f.name}: unsupported file type.`);
      }
    }
    if (problems.length) setNotice({ text: problems.join("\n"), error: true });
  }, [selectedCase, newCase, stageDocs, extract]);

  async function confirmScan(s: Scan, r: ReviewResult) {
    if (!selectedCase || !s.record) return;
    setBusy(true);
    try {
      const out = await c3.confirmC1(selectedCase, [{ ...s.record, doc_type: r.docType,
        period_year: r.periodYear, parent_doc_id: r.parentDocId, fields: r.fields }]);
      stageDocs(selectedCase, out.case.docs);
      setScans((prev) => prev.filter((x) => x.key !== s.key));
      const raises = out.issues.length ? `\nIt will raise:\n- ${out.issues.join("\n- ")}` : "";
      setNotice({ text: `${s.name} added to ${selectedCase}.${raises}` });
    } catch (e) {
      setNotice({ text: e instanceof Error ? e.message : "Could not add the document.", error: true });
    }
    setBusy(false);
  }

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
    <div style={{ maxWidth: "640px", margin: "0 auto", padding: "48px 24px 64px", width: "100%" }}>
      <h1 className="heading-serif" style={{ fontSize: "42px", textAlign: "center", marginBottom: "8px" }}>
        Your Library
      </h1>
      <p style={{ textAlign: "center", color: "var(--text-muted)", fontSize: "15px", marginBottom: "28px" }}>
        Add documents to a case and audit them.
      </p>

      {/* Target case */}
      <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "20px", fontSize: "14px" }}>
        <span style={{ color: "var(--text-muted)" }}>Case</span>
        <select value={selectedCase ?? ""} onChange={(e) => setCase(e.target.value || null)} style={selectStyle}>
          <option value="">Choose a case…</option>
          {caseOptions.map((id) => <option key={id} value={id}>{id}{audited.has(id) ? "" : " (new)"}</option>)}
        </select>
        <button onClick={() => newCase()} style={pillButton}>New case</button>
      </div>

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => { e.preventDefault(); setIsDragging(false); if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files); }}
        onClick={() => inputRef.current?.click()}
        style={{
          border: `2px dashed ${isDragging ? "var(--text-muted)" : "var(--border)"}`, borderRadius: "var(--radius-lg)",
          padding: "40px 24px", textAlign: "center", marginBottom: "24px",
          background: isDragging ? "var(--accent-bg)" : "transparent", transition: "all 0.2s ease", cursor: "pointer",
        }}
      >
        <div style={{ marginBottom: "12px" }}>
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" style={{ margin: "0 auto" }}>
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
        </div>
        <p style={{ fontWeight: 500, color: "var(--text-h)", fontSize: "15px", marginBottom: "4px" }}>Drag and drop files here</p>
        <p style={{ color: "var(--text-soft)", fontSize: "13px", marginBottom: "16px" }}>
          JSON documents{c1.enabled() ? ", or PDF / PNG / JPG scans" : ""}
        </p>
        <button onClick={(e) => { e.stopPropagation(); inputRef.current?.click(); }} style={pillButton}>Choose files</button>
        <input ref={inputRef} type="file" multiple style={{ display: "none" }}
               accept={c1.enabled() ? ".json,.pdf,.png,.jpg,.jpeg" : ".json"}
               onChange={(e) => { if (e.target.files) handleFiles(e.target.files); e.target.value = ""; }} />
      </div>

      {notice && (
        <p style={{
          whiteSpace: "pre-wrap", fontSize: "13px", marginBottom: "20px", padding: "10px 14px",
          borderRadius: "var(--radius)", border: `1px solid ${notice.error ? "var(--danger)" : "var(--border-light)"}`,
          color: notice.error ? "var(--danger)" : "var(--text)", background: "var(--surface)",
        }}>{notice.text}</p>
      )}

      {/* Scans: C1 extraction, then the reviewer checks what C3 read */}
      {scans.length > 0 && (
        <Section title="Scans">
          {scans.map((s) => s.state === "review" && s.preview ? (
            <ReviewPanel key={s.key} name={s.name} preview={s.preview} busy={busy}
                         parents={docs.map((d) => d.doc_id)}
                         onConfirm={(r) => confirmScan(s, r)}
                         onReread={(docType) => s.record && readScan(s.key, s.record, docType)}
                         onDiscard={() => setScans((prev) => prev.filter((x) => x.key !== s.key))} />
          ) : (
            <Row key={s.key} title={s.name}
                 meta={s.state === "error" ? s.message ?? "" : SCAN_STATE[s.state]}
                 error={s.state === "error"}
                 onRemove={() => setScans((prev) => prev.filter((x) => x.key !== s.key))} />
          ))}
        </Section>
      )}

      {/* Documents waiting to be audited */}
      {selectedCase && (
        <Section title={`Documents for ${selectedCase}`}>
          {docs.length === 0 && <p style={{ fontSize: "13px", color: "var(--text-muted)" }}>No documents added yet.</p>}
          {docs.map((d) => (
            <Row key={d.doc_id} title={d.doc_id}
                 meta={`${d.doc_type.replace(/_/g, " ")} · ${d.period_year} · ${Object.keys(d.fields).length} field(s)`
                       + (d.parent_doc_id ? ` · supports ${d.parent_doc_id}` : "")}
                 onRemove={() => unstage(selectedCase, d.doc_id)} />
          ))}
          {docs.length > 0 && (
            <div style={{ display: "flex", gap: "8px", marginTop: "16px" }}>
              <button onClick={audit} disabled={busy} style={{ ...pillButton, background: "var(--text-h)", color: "#f5f0ea", border: "none" }}>
                {busy ? "Auditing…" : audited.has(selectedCase) ? `Add ${docs.length} to the case and re-audit` : `Audit ${docs.length} document(s)`}
              </button>
              <button onClick={() => navigate(routes.dashboard)} style={pillButton}>Open chat</button>
            </div>
          )}
          {docs.length === 0 && audited.has(selectedCase) && (
            <button onClick={() => navigate(routes.dashboard)} style={{ ...pillButton, marginTop: "12px" }}>Open chat</button>
          )}
        </Section>
      )}
    </div>
  );
}

const selectStyle: React.CSSProperties = {
  padding: "6px 10px", borderRadius: "var(--radius)", border: "1px solid var(--border)",
  background: "var(--surface)", color: "var(--text-h)", fontSize: "13px", fontFamily: "inherit",
};

const pillButton: React.CSSProperties = {
  padding: "8px 18px", borderRadius: "var(--radius-pill)", border: "1px solid var(--border)",
  background: "var(--surface)", color: "var(--text-h)", fontSize: "13px", fontWeight: 500,
  cursor: "pointer", fontFamily: "inherit",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: "28px" }}>
      <h3 style={{ fontWeight: 600, fontSize: "16px", color: "var(--text-h)", marginBottom: "12px" }}>{title}</h3>
      <div style={{ display: "flex", flexDirection: "column" }}>{children}</div>
    </div>
  );
}

function Row({ title, meta, error, onRemove, children }: {
  title: string; meta: string; error?: boolean; onRemove: () => void; children?: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: "14px", padding: "12px 0", borderBottom: "1px solid var(--border-light)" }}>
      <div style={{ flexShrink: 0, color: "var(--text-muted)", paddingTop: "2px" }}>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
        </svg>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="id" style={{ fontWeight: 500, fontSize: "14px", color: "var(--text-h)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</div>
        <div style={{ fontSize: "12px", color: error ? "var(--danger)" : "var(--text-muted)", marginTop: "2px" }}>{meta}</div>
        {children}
      </div>
      <button onClick={onRemove} title="Remove"
              style={{ flexShrink: 0, background: "none", border: "none", cursor: "pointer", color: "var(--text-soft)", padding: "4px" }}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="3 6 5 6 21 6" />
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
        </svg>
      </button>
    </div>
  );
}
