// Component-03 contract (Backend/Component-03/app/schemas). Keep in step with the backend.

export interface AuditDocument {
  doc_id: string;
  case_id?: string;
  doc_type: string; // a Component-02 DocumentType code, or "unknown"
  period_year: number;
  parent_doc_id?: string | null;
  fields: Record<string, number | string | null>;
  confidences?: Record<string, number>;
  methods?: Record<string, string>;
  // Upstream record the values came from; verified_version null = not human-verified.
  source?: { component: string; document_id: string; run_id: string | null;
             verified_version: number | null; confirmed_by: string | null } | null;
}

export interface AuditCase {
  case_id: string;
  docs: AuditDocument[];
  // Amount below which a difference is not material (SLAuS 320). Findings below it
  // stay, at low severity. Omitted = every difference counts.
  materiality?: number | null;
}

export type FindingCategory = "arithmetic" | "ledger" | "format" | "compliance" | "possible_fraud";
export type Severity = "low" | "medium" | "high";
export type ReviewStatus = "pending_review" | "confirmed" | "dismissed" | "needs_more_evidence";
export type EvidenceValidation = "unverified" | "passed" | "existence_only" | "failed";
export type AuditStatus = "pending_auditor_review" | "not_auditable";

export interface EvidenceClaim {
  evidence_id: string;
  field: string;
  claimed_value: number | string;
}

export interface Finding {
  finding_id: string;
  rule_id: string; // CHK-*/POL-* from the knowledge graph, REV-* review items
  category: FindingCategory;
  severity: Severity;
  message: string;
  evidence_ids: string[];
  policy_ids: string[];
  confidence: number;
  review_status: ReviewStatus;
  claims: EvidenceClaim[];
  reasoning_chain: string[];
  evidence_validation: EvidenceValidation;
  citation_unverified: boolean;
  supersedes: number | null;
  created_at: string;
}

export interface TraceEntry {
  agent_name: string;
  decision_type: string;
  detail: string;
  seq: number;
}

export interface AuditResult {
  case_id: string;
  version: number;
  kg_source: string;
  latency_ms: number;
  status: AuditStatus;
  findings: Finding[];
  trace: TraceEntry[];
  rejected_records: string[];
  rejected_citations: string[];
  events_published: boolean;
  created_at: string;
}

export interface CaseSummary {
  case_id: string;
  version: number;
  status: AuditStatus;
  created_at: string;
  docs: number;
  findings: number;
  high: number;
  needs_review: number;
  materiality: number | null;
}

export type CopilotGroup = "rule_query" | "case_query" | "evidence_append" | "fresh_audit" | "other";

export interface CopilotRequest {
  text: string;
  case_id?: string | null;
  session_id?: string | null; // saves the turn and lets follow-ups use the chat's memory
  docs?: AuditDocument[];
}

export interface CopilotResponse {
  intent: string; // fine-grained intent, e.g. list_findings, whatif_check
  group: CopilotGroup;
  reply: string;
  session_id: string | null;
  suggestions: string[];
  data: (Record<string, unknown> & { findings?: Finding[]; version?: number; needs?: string }) | null;
}

// Saved chat (Component-03 /chat). A case's own chat has session_id === case_id.
export type ChatRole = "user" | "copilot" | "report" | "system";

export interface ChatMessage {
  message_id: string;
  session_id: string;
  seq: number;
  case_id: string | null;
  role: ChatRole;
  text: string;
  intent: string | null;
  group: CopilotGroup | null;
  suggestions: string[];
  refs: { version: number | null; finding_ids: string[] } | null;
  findings: Finding[]; // filled in by the server from the saved audit version
  data: Record<string, unknown> & { attached_docs?: number; report_url?: string };
  source: string;
  created_at: string;
}

export interface ChatSession {
  session_id: string;
  case_id: string | null;
  title: string;
  created_at: string;
  updated_at: string;
}
