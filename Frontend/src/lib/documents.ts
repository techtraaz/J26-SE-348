import type { AuditResult } from "@/types/audit";

// Component-02 DocumentType codes (same list as C3 config.ALLOWED_DOC_TYPES).
export const DOC_TYPES = [
  "balance_sheet", "income_statement", "cash_flow_statement", "equity_statement",
  "trial_balance", "general_ledger", "invoice", "receipt", "payment_voucher",
  "bank_statement", "purchase_order", "goods_received_note", "fixed_asset_register", "payroll",
] as const;

// Case documents come only from verified Component-01 documents (D16), picked in
// the chat (features/documents/VerifiedDocumentPicker). The JSON attach is gone.

/** One-line summary of a finished audit. */
export function auditSummary(r: AuditResult): string {
  const rule = r.findings.filter((f) => !f.rule_id.startsWith("REV-"));
  const reviews = r.findings.filter((f) => f.review_status === "needs_more_evidence").length;
  const high = rule.filter((f) => f.severity === "high").length;
  if (r.status === "not_auditable") return `Case ${r.case_id} version ${r.version} is not auditable; see the chat for the reasons.`;
  const rejected = r.rejected_records.length ? ` Rejected documents: ${r.rejected_records.join(", ")}.` : "";
  return `Case ${r.case_id} version ${r.version} saved: ${rule.length} rule finding(s) (${high} high), `
    + `${reviews} need review.${rejected} The result is in the case's chat.`;
}
