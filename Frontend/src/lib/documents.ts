import type { AuditDocument, AuditResult, Finding } from "@/types/audit";

// Component-02 DocumentType codes (same list as C3 config.ALLOWED_DOC_TYPES).
export const DOC_TYPES = [
  "balance_sheet", "income_statement", "cash_flow_statement", "equity_statement",
  "trial_balance", "general_ledger", "invoice", "receipt", "payment_voucher",
  "bank_statement", "purchase_order", "goods_received_note", "fixed_asset_register", "payroll",
] as const;

export const isJsonFile = (f: File) => f.name.toLowerCase().endsWith(".json") || f.type === "application/json";
export const isScan = (f: File) => /\.(pdf|png|jpe?g)$/i.test(f.name);

function asDocument(raw: unknown, where: string): AuditDocument {
  const d = raw as Partial<AuditDocument> | null;
  if (!d || typeof d !== "object") throw new Error(`${where}: not a document object`);
  if (typeof d.doc_id !== "string" || !d.doc_id) throw new Error(`${where}: doc_id is missing`);
  if (typeof d.period_year !== "number") throw new Error(`${where}: period_year is missing`);
  if (!d.fields || typeof d.fields !== "object") throw new Error(`${where}: fields is missing`);
  return {
    doc_id: d.doc_id, doc_type: d.doc_type ?? "unknown", period_year: d.period_year,
    parent_doc_id: d.parent_doc_id ?? null, fields: d.fields,
    confidences: d.confidences ?? {}, methods: d.methods ?? {},
  };
}

/** A JSON file may hold a case {case_id, docs}, a list of documents, or one document.
 *  C3 does the full validation; this only catches files that are clearly not documents. */
export async function readJsonDocuments(file: File): Promise<AuditDocument[]> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(await file.text());
  } catch {
    throw new Error(`${file.name}: not valid JSON`);
  }
  const list = Array.isArray(parsed) ? parsed
    : parsed && typeof parsed === "object" && Array.isArray((parsed as { docs?: unknown }).docs)
      ? (parsed as { docs: unknown[] }).docs
      : [parsed];
  if (list.length === 0) throw new Error(`${file.name}: no documents`);
  return list.map((d, i) => asDocument(d, `${file.name} [${i + 1}]`));
}

/** Chat text for a finished audit. */
export function auditSummary(r: AuditResult): { content: string; findings: Finding[] } {
  const rule = r.findings.filter((f) => !f.rule_id.startsWith("REV-"));
  const reviews = r.findings.filter((f) => f.review_status === "needs_more_evidence").length;
  const high = rule.filter((f) => f.severity === "high").length;
  const head = r.status === "not_auditable"
    ? `Case ${r.case_id} version ${r.version} is not auditable. The reasons are below.`
    : `Case ${r.case_id} version ${r.version} saved: ${rule.length} rule finding(s) (${high} high), ${reviews} need review.`;
  const rejected = r.rejected_records.length ? `\nRejected documents: ${r.rejected_records.join(", ")}.` : "";
  return { content: head + rejected, findings: r.findings };
}
