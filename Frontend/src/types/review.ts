// Library review of Component-01 documents (C3 /audit/intake/c1/preview and /confirm).

// A C1 document as C3 receives it: the verified record when a person verified it, else the extraction.
export type C1Record = { verified: unknown } | { extraction: unknown };

export interface LineRef {
  line_id: string;
  page: number;
  text: string;
  confidence: number | null;
  box: number[] | null;
}

export interface PreviewField {
  field: string;
  value: number | string;
  method: "rules" | "llm";
  label: string;
  needs_confirmation: boolean;
  confidence: number;
  line: LineRef;
  label_line: LineRef | null;
  alternatives: { value: number | string; line_id: string }[];
}

export interface Suggestion {
  value: string | number;
  evidence: string;
  line_id: string;
}

export interface DocumentPreview {
  document_id: string;
  human_verified: boolean;
  source: { component: string; document_id: string; run_id: string | null;
            verified_version: number | null; confirmed_by: string | null };
  suggestions: { doc_type: Suggestion | null; period_year: Suggestion | null };
  doc_type: string;
  fields: PreviewField[];
  unmapped_lines: (LineRef & { value: number | null })[];
  missing_fields: string[];
  rules_not_runnable: { rule_id: string; missing: string[] }[];
  field_names: string[];
  llm: { used: boolean; error: string | null };
  line_count: number;
}

export interface FieldDecision {
  field: string;
  line_id?: string;
  value?: number | string; // only when the reviewer typed or changed it
  confirmed?: boolean;
}
