import { useMemo, useState } from "react";
import { DOC_TYPES } from "@/lib/documents";
import type { DocumentPreview, FieldDecision } from "@/types/review";

// One field row as the reviewer sees it.
interface Row {
  key: string;
  field: string;
  lineId?: string;
  lineText: string;
  readValue: string; // what C3 read from the line
  value: string; // what the reviewer sees and may change
  ai: boolean; // matched by the LLM
  picked: boolean; // added by the reviewer
  confirmed: boolean;
  confidence: number | null;
}

export interface ReviewResult {
  docType: string;
  periodYear: number;
  parentDocId: string | null;
  fields: FieldDecision[];
}

function initialRows(p: DocumentPreview): Row[] {
  return p.fields.map((f) => ({
    key: `${f.field}-${f.line.line_id}`, field: f.field, lineId: f.line.line_id,
    lineText: f.label_line ? `${f.label_line.text}  →  ${f.line.text}` : f.line.text,
    readValue: String(f.value), value: String(f.value), ai: f.method === "llm", picked: false,
    confirmed: false, confidence: f.confidence,
  }));
}

/** Check what C3 read from a C1 document before it goes into the case. */
export function ReviewPanel({ name, preview, parents, busy, onConfirm, onReread, onDiscard }: {
  name: string;
  preview: DocumentPreview;
  parents: string[];
  busy: boolean;
  onConfirm: (r: ReviewResult) => void;
  onReread: (docType: string) => void;
  onDiscard: () => void;
}) {
  const p = preview;
  const [docType, setDocType] = useState(p.doc_type === "unknown" ? "" : p.doc_type);
  const [year, setYear] = useState<string>(p.suggestions.period_year ? String(p.suggestions.period_year.value) : "");
  const [parent, setParent] = useState("");
  const [rows, setRows] = useState<Row[]>(() => initialRows(p));
  const [addField, setAddField] = useState("");
  const [addLine, setAddLine] = useState("");

  const used = useMemo(() => new Set(rows.map((r) => r.lineId)), [rows]);
  const openLines = p.unmapped_lines.filter((l) => !used.has(l.line_id));
  const missing = p.missing_fields.filter((m) => !rows.some((r) => r.field === m));
  const unconfirmedAi = rows.filter((r) => r.ai && !r.confirmed && r.value === r.readValue).length;
  const yearOk = /^\d{4}$/.test(year);

  const update = (key: string, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  function add() {
    const line = p.unmapped_lines.find((l) => l.line_id === addLine);
    if (!addField || rows.some((r) => r.field === addField)) return;
    const value = line?.value != null ? String(line.value) : "";
    setRows((rs) => [...rs, { key: `${addField}-${addLine || "typed"}`, field: addField, lineId: line?.line_id,
      lineText: line?.text ?? "typed by you", readValue: value, value, ai: false, picked: true,
      confirmed: true, confidence: line?.confidence ?? null }]);
    setAddField(""); setAddLine("");
  }

  function confirm() {
    onConfirm({
      docType, periodYear: Number(year), parentDocId: parent || null,
      fields: rows.map((r) => {
        const typed = r.value !== r.readValue || !r.lineId;
        return { field: r.field, line_id: r.lineId, confirmed: r.confirmed || r.picked,
                 ...(typed ? { value: r.value } : {}) };
      }),
    });
  }

  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "16px", marginBottom: "16px", background: "var(--surface)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
        <span className="id" style={{ fontWeight: 600, color: "var(--text-h)" }}>{name}</span>
        <Badge tone={p.human_verified ? "ok" : "warn"}>
          {p.human_verified
            ? `Human-verified in C1 (v${p.source.verified_version}${p.source.confirmed_by ? ` by ${p.source.confirmed_by}` : ""})`
            : "Not human-verified in C1"}
        </Badge>
        <span style={{ fontSize: "12px", color: "var(--text-soft)" }}>{p.line_count} lines read</span>
      </div>

      {/* Type, year, parent */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 110px 1fr", gap: "8px", marginTop: "12px", fontSize: "12px" }}>
        <label style={labelStyle}>Document type
          <select value={docType} onChange={(e) => setDocType(e.target.value)} style={inputStyle}>
            <option value="">Choose…</option>
            {DOC_TYPES.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
          </select>
        </label>
        <label style={labelStyle}>Year
          <input value={year} onChange={(e) => setYear(e.target.value.trim())} placeholder="YYYY" style={inputStyle} />
        </label>
        <label style={labelStyle}>Supports (optional)
          <select value={parent} onChange={(e) => setParent(e.target.value)} style={inputStyle}>
            <option value="">None</option>
            {parents.filter((d) => d !== p.document_id).map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </label>
      </div>
      <p style={hintStyle}>
        {p.suggestions.doc_type ? `Type suggested from "${p.suggestions.doc_type.evidence}". ` : "No type found in the text. "}
        {p.suggestions.period_year ? `Year suggested from "${p.suggestions.period_year.evidence}".` : "No year found; enter it."}
        {docType && docType !== p.doc_type && (
          <button onClick={() => onReread(docType)} disabled={busy} style={linkButton}>Re-read as {docType.replace(/_/g, " ")}</button>
        )}
      </p>

      {/* Fields */}
      <div style={{ marginTop: "12px", display: "flex", flexDirection: "column", gap: "6px" }}>
        {rows.length === 0 && <p style={hintStyle}>No fields were read.</p>}
        {rows.map((r) => (
          <div key={r.key} style={{ display: "grid", gridTemplateColumns: "150px 120px 1fr auto", gap: "8px", alignItems: "center", fontSize: "13px" }}>
            <span className="id" style={{ color: "var(--text-h)" }}>{r.field}</span>
            <input value={r.value} onChange={(e) => update(r.key, { value: e.target.value })} style={inputStyle} />
            <span style={{ color: "var(--text-muted)", fontSize: "12px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                  title={r.lineText}>
              {r.lineText}{r.confidence != null ? ` · ${r.confidence.toFixed(2)}` : ""}
            </span>
            <span style={{ display: "flex", gap: "6px", alignItems: "center" }}>
              {r.ai ? (
                <label style={{ fontSize: "12px", color: r.confirmed ? "var(--text-h)" : "var(--warning)", display: "flex", gap: "4px", alignItems: "center" }}>
                  <input type="checkbox" checked={r.confirmed} onChange={(e) => update(r.key, { confirmed: e.target.checked })} />
                  AI match · confirm
                </label>
              ) : <Badge tone="muted">{r.picked ? "added" : "rules"}</Badge>}
              <button onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))} title="Remove" style={linkButton}>×</button>
            </span>
          </div>
        ))}
      </div>

      {missing.length > 0 && (
        <p style={{ ...hintStyle, color: "var(--warning)" }}>
          Required but not found: {missing.join(", ")}. Add it below from a line, or type the value.
        </p>
      )}
      {p.rules_not_runnable.length > 0 && (
        <p style={hintStyle}>
          Not on this document, so these checks will not run: {p.rules_not_runnable.map((r) => `${r.rule_id} (${r.missing.join(", ")})`).join("; ")}.
        </p>
      )}
      {p.llm.error && <p style={hintStyle}>AI matching was not available: {p.llm.error}</p>}

      {/* Add a field */}
      <div style={{ display: "flex", gap: "6px", marginTop: "10px", flexWrap: "wrap" }}>
        <input list={`fields-${p.document_id}`} value={addField} onChange={(e) => setAddField(e.target.value)}
               placeholder="Field name" style={{ ...inputStyle, width: "170px" }} />
        <datalist id={`fields-${p.document_id}`}>
          {p.field_names.map((f) => <option key={f} value={f} />)}
        </datalist>
        <select value={addLine} onChange={(e) => setAddLine(e.target.value)} style={{ ...inputStyle, flex: 1, minWidth: "180px" }}>
          <option value="">Type the value myself</option>
          {openLines.map((l) => <option key={l.line_id} value={l.line_id}>{l.text}</option>)}
        </select>
        <button onClick={add} disabled={!p.field_names.includes(addField)} style={pillButton}>Add field</button>
      </div>

      <div style={{ display: "flex", gap: "8px", marginTop: "14px", alignItems: "center", flexWrap: "wrap" }}>
        <button onClick={confirm} disabled={busy || !docType || !yearOk}
                style={{ ...pillButton, background: "var(--primary)", color: "var(--on-primary)", border: "none" }}>
          Add to case
        </button>
        <button onClick={onDiscard} disabled={busy} style={pillButton}>Discard</button>
        {unconfirmedAi > 0 && (
          <span style={{ fontSize: "12px", color: "var(--warning)" }}>
            {unconfirmedAi} AI match(es) not confirmed: they will be audited as needing review.
          </span>
        )}
        {!yearOk && <span style={{ fontSize: "12px", color: "var(--text-soft)" }}>Enter the year to continue.</span>}
      </div>
    </div>
  );
}

function Badge({ tone, children }: { tone: "ok" | "warn" | "muted"; children: React.ReactNode }) {
  const color = tone === "ok" ? "var(--success)" : tone === "warn" ? "var(--warning)" : "var(--text-muted)";
  return <span style={{ fontSize: "11px", borderRadius: "var(--radius-pill)", padding: "1px 8px", border: `1px solid ${color}`, color }}>{children}</span>;
}

const labelStyle: React.CSSProperties = { display: "flex", flexDirection: "column", gap: "4px", color: "var(--text-muted)" };
const inputStyle: React.CSSProperties = {
  padding: "6px 8px", borderRadius: "var(--radius)", border: "1px solid var(--border)",
  background: "var(--bg)", color: "var(--text-h)", fontSize: "13px", fontFamily: "inherit",
};
const hintStyle: React.CSSProperties = { fontSize: "12px", color: "var(--text-muted)", margin: "8px 0 0" };
const linkButton: React.CSSProperties = {
  background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)",
  fontSize: "12px", fontFamily: "inherit", padding: "0 4px", textDecoration: "underline",
};
const pillButton: React.CSSProperties = {
  padding: "7px 16px", borderRadius: "var(--radius-pill)", border: "1px solid var(--border)",
  background: "var(--surface)", color: "var(--text-h)", fontSize: "13px", fontWeight: 500,
  cursor: "pointer", fontFamily: "inherit",
};
