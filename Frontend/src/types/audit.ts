// Agreed JSON shapes. From Component-03 schemas + mock_data.json.
export type DocType = "balance_sheet" | "income_statement" | "invoice" | "receipt" | "unknown";

export interface AuditDocument {
  doc_id: string;
  case_id: string;
  doc_type: DocType | string;
  period_year: number;
  parent_doc_id?: string | null;
  fields: Record<string, number | string | null>;
  confidences?: Record<string, number>;
  methods?: Record<string, string>;
}

export interface AuditCase {
  case_id: string;
  docs: AuditDocument[];
}

export type FindingCategory = "arithmetic" | "ledger" | "format" | "compliance" | "possible_fraud";
export type Severity = "low" | "medium" | "high";
export type ReviewStatus = "pending_review" | "confirmed" | "dismissed" | "needs_more_evidence";

export interface Finding {
  finding_id: string;
  rule_id: string;
  category: FindingCategory;
  severity: Severity;
  message: string;
  evidence_ids: string[];
  policy_ids: string[];
  confidence: number;
  review_status?: ReviewStatus;
}

export interface TraceEntry {
  agent_name: string;
  decision_type: string;
  detail: string;
}

export interface AuditResult {
  case_id: string;
  version: number;
  status: string;
  findings: Finding[];
  trace: TraceEntry[];
}

export type CopilotIntent = "rule_query" | "evidence_append" | "fresh_audit";
