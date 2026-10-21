import type { PolicyRun, PolicyRunBrief, Stage } from "@/types/policies";

// The steps of a KG update, in order. "stored" happens in the upload request itself.
export type StepId = "stored" | Stage;
export type StepState = "done" | "running" | "pending" | "failed" | "skipped" | "warning";

export const STEPS: { id: StepId; label: string; hint: string }[] = [
  { id: "stored", label: "Stored", hint: "Saved in object storage" },
  { id: "chunk", label: "Paragraphs", hint: "Text read and split into numbered paragraphs" },
  { id: "classify", label: "Classified", hint: "Standard, amendment or Act" },
  { id: "retrieve_context", label: "Graph context", hint: "What the graph already holds" },
  { id: "extract", label: "LLM extraction", hint: "Requirements, definitions and equations" },
  { id: "validate", label: "Validated", hint: "Checked against the ontology" },
  { id: "resolve", label: "Matched", hint: "Matched with nodes already in the graph" },
  { id: "write", label: "Written", hint: "Merged into the knowledge graph" },
];

// Document kinds the pipeline adds to the graph; anything else stops after "classify".
export const KG_KINDS = ["standard", "amendment", "legislation"];

export const runKey = (name: string) => ["c2", "run", name];

export const isActive = (run: { status: string } | null | undefined) =>
  run?.status === "queued" || run?.status === "running";

export function stepStates(run: PolicyRun | null): Record<StepId, StepState> {
  const out = { stored: "done" } as Record<StepId, StepState>;
  const stages = STEPS.slice(1).map((s) => s.id as Stage);
  // runs saved before stages were recorded only have a status
  const done = new Set(run?.stages_done ?? (run?.status === "done" ? stages : []));
  for (const id of stages) {
    if (!run) out[id] = "pending";
    else if (done.has(id)) out[id] = id === "extract" && run.summary?.llm_unavailable ? "warning" : "done";
    else if (run.stage === id) out[id] = run.status === "failed" ? "failed" : "running";
    else out[id] = run.status === "done" ? "skipped" : "pending";
  }
  return out;
}

const STEP_LABEL = Object.fromEntries(STEPS.map((s) => [s.id, s.label])) as Record<StepId, string>;

/** One line for the list and the detail header. */
export function runLine(run: PolicyRunBrief | null): { tone: "info" | "success" | "warning" | "danger" | "muted"; text: string } {
  if (!run) return { tone: "muted", text: "Not in the graph yet" };
  if (run.status === "queued") return { tone: "info", text: "Waiting to start" };
  if (run.status === "running") {
    const step = run.stage ? STEP_LABEL[run.stage] : "Starting";
    const p = run.stage === "extract" && run.progress?.total ? ` ${run.progress.done}/${run.progress.total}` : "";
    return { tone: "info", text: `${step}${p}` };
  }
  if (run.status === "failed") return { tone: "danger", text: "Update failed" };
  if (run.kind && !KG_KINDS.includes(run.kind)) return { tone: "muted", text: "Not added: not a standard" };
  if (run.llm_unavailable) return { tone: "warning", text: "Added without LLM extraction" };
  const added = run.added ? `+${run.added.nodes} nodes` : "In the graph";
  return { tone: "success", text: added };
}
