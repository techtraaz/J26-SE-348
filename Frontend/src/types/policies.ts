// Component-02 policies: PDFs kept in object storage and added to the knowledge graph.

export type RunStatus = "queued" | "running" | "done" | "failed";

export type Stage = "chunk" | "classify" | "retrieve_context" | "extract" | "validate" | "resolve" | "write";

export interface Totals {
  nodes: number;
  relationships: number;
}

// One row of GET /policies.
export interface PolicyRunBrief {
  job_id: string | null;
  status: RunStatus;
  stage: Stage | null;
  progress: { done: number; total: number } | null;
  kind: string | null;
  code: string | null;
  error: string | null;
  finished_at: string | null;
  added: Totals | null;
  requirements: number | null;
  definitions: number | null;
  equations: number | null;
  llm_unavailable: string | null;
}

export interface Policy {
  name: string;
  size_bytes: number;
  uploaded_at: string;
  last_run: PolicyRunBrief | null;
}

export interface GraphNode {
  id: string; // "Label:key"
  label: string;
  key: string;
  caption: string;
  new: boolean;
}

export interface GraphLink {
  source: string;
  target: string;
  type: string;
}

export interface NewItem {
  key: string;
  caption: string;
  section: string | null;
}

export interface KgChanges {
  new: Record<string, NewItem[]>;
  graph: { nodes: GraphNode[]; links: GraphLink[]; truncated: boolean };
}

export interface RunSummary {
  chunks: number;
  sent_to_llm: number;
  skipped: number;
  llm_errors: number;
  llm_unavailable: string | null;
  requirements: number;
  definitions: number;
  equations: number;
  created: Record<string, number>;
  matched: Record<string, number>;
  proposals: number;
  plan_errors: string[];
  written: number;
}

// GET /policies/{name}/run: the running job, or the last one saved next to the PDF.
export interface PolicyRun {
  job_id: string;
  file: string;
  code: string | null;
  status: RunStatus;
  kind?: string | null;
  stage?: Stage | null;
  stages_done?: Stage[];
  progress?: { done: number; total: number } | null;
  error?: string | null;
  summary?: RunSummary;
  changes?: KgChanges;
  totals?: { before: Totals | null; after: Totals | null };
  queued_at: string;
  started_at?: string;
  finished_at?: string;
}
