// Builds the Thinking timeline from Component-04's live XAI events.
//
// C04 streams one event per stage change or step, already worded (verb,
// target, detail, facts). This file only groups them: runs (one audit or one
// Copilot turn) -> stages (agents) -> steps, and writes the short summaries
// shown on collapsed rows ("Compliance · evaluated 12 checks, 2 failed").

export type Tone = "danger" | "warning" | "success" | "muted" | "neutral";

export interface XaiFact {
  label: string;
  value: string;
}

/** One SSE payload from C04 (/xai/stream/{id}). */
export interface XaiEvent {
  event_type: string;
  case_id?: string;
  run_key?: string;
  run_kind?: string;
  version?: number;
  seq?: number;
  stage?: string | null;
  label?: string;
  kind?: string;
  status?: string | null;
  tone?: Tone;
  verb?: string;
  target?: string;
  detail?: string;
  facts?: XaiFact[];
  check?: boolean;
  duration_ms?: number | null;
  findings_count?: number | null;
  total_findings?: number | null;
  doc_count?: number;
  summary?: string;
  error?: string | null;
  // Review Agent (insight_summary)
  verdict?: Verdict;
  headline?: string;
  next_steps?: string[];
  source?: "ai" | "rules";
  model?: string | null;
}

export type Verdict = "clear" | "review" | "action_required";

/** The Review Agent's verdict on one audit run. */
export interface Review {
  pending: boolean;
  verdict: Verdict | null;
  headline: string;
  summary: string;
  nextSteps: string[];
  source: "ai" | "rules" | null;
  model: string | null;
}

export interface Step {
  id: string;
  kind: string;
  status: string;
  tone: Tone;
  verb: string;
  target: string;
  detail: string;
  facts: XaiFact[];
  check: boolean;
}

export type Status = "running" | "done" | "error";

export interface Stage {
  id: string;
  label: string;
  status: Status;
  durationMs: number | null;
  note: string; // the agent's own one-line summary, when it finishes
  findings: number | null;
  steps: Step[];
}

export interface Run {
  key: string;
  kind: "audit" | "copilot";
  caseId: string;
  version: number | null;
  status: Status;
  question: string; // Copilot: what was asked
  answer: string; // Copilot: the reply, as one short line
  docCount: number | null;
  totalFindings: number | null;
  durationMs: number | null;
  review: Review | null;
  stages: Stage[];
}

const READ_KINDS = new Set(["evidence_read"]);
const LOOKUP_KINDS = new Set(["kg_fetch"]);

function newRun(e: XaiEvent, key: string): Run {
  return {
    key,
    kind: e.run_kind === "copilot" ? "copilot" : "audit",
    caseId: e.case_id ?? "",
    version: e.run_kind === "copilot" ? null : (e.version ?? null),
    status: "running",
    question: "",
    answer: "",
    docCount: null,
    totalFindings: null,
    durationMs: null,
    review: null,
    stages: [],
  };
}

function stageOf(run: Run, e: XaiEvent): Stage {
  const id = e.stage ?? "pipeline";
  let stage = run.stages.find((s) => s.id === id);
  if (!stage) {
    stage = { id, label: e.label ?? id, status: "running", durationMs: null, note: "", findings: null, steps: [] };
    run.stages.push(stage);
  }
  if (e.label) stage.label = e.label;
  return stage;
}

/** Group a stream's events into runs, oldest first. Pure: same events, same runs. */
export function buildRuns(events: XaiEvent[]): Run[] {
  const runs = new Map<string, Run>();
  let n = 0;

  for (const e of events) {
    n += 1;
    if (e.event_type === "insight_pending" || e.event_type === "insight_summary") {
      // The Review Agent's verdict on a finished audit (older events carry no run_key:
      // they belong to that case's latest audit run).
      const target = (e.run_key && runs.get(e.run_key))
        || [...runs.values()].reverse().find((r) => r.kind === "audit" && r.caseId === e.case_id);
      if (target) target.review = toReview(e);
      continue;
    }
    const key = e.run_key ?? `${e.case_id ?? "stream"}:${e.version ?? 0}`;
    let run = runs.get(key);
    if (!run) {
      run = newRun(e, key);
      runs.set(key, run);
    }

    switch (e.event_type) {
      case "pipeline_start":
        run.docCount = e.doc_count ?? null;
        break;
      case "run_start":
        run.question = e.detail ?? "";
        break;
      case "agent_thinking":
        stageOf(run, e).status = "running";
        break;
      case "step": {
        const stage = stageOf(run, e);
        stage.steps.push({
          id: `${key}:${n}`,
          kind: e.kind ?? "step",
          status: e.status ?? "info",
          tone: e.tone ?? "neutral",
          verb: e.verb ?? "",
          target: e.target ?? "",
          detail: e.detail ?? "",
          facts: e.facts ?? [],
          check: Boolean(e.check),
        });
        break;
      }
      case "agent_done": {
        const stage = stageOf(run, e);
        stage.status = "done";
        stage.durationMs = e.duration_ms ?? stage.durationMs;
        stage.note = e.detail ?? "";
        stage.findings = e.findings_count ?? null;
        break;
      }
      case "agent_error": {
        const stage = stageOf(run, e);
        stage.status = "error";
        stage.note = e.detail ?? e.error ?? "";
        run.status = "error";
        break;
      }
      case "pipeline_end":
        run.totalFindings = e.total_findings ?? null;
        finish(run);
        break;
      case "run_end":
        run.answer = oneLine(e.detail ?? "");
        run.durationMs = e.duration_ms ?? null;
        finish(run);
        break;
      default:
        break;
    }
  }
  return [...runs.values()];
}

function toReview(e: XaiEvent): Review {
  const pending = e.event_type === "insight_pending";
  return {
    pending,
    verdict: e.verdict ?? null,
    headline: e.headline ?? "",
    summary: pending ? "" : (e.summary ?? e.detail ?? ""),
    nextSteps: e.next_steps ?? [],
    source: e.source ?? (pending ? null : "ai"),
    model: e.model ?? null,
  };
}

/** A reply as one readable line: list markers and a bare "I can:" lead-in are dropped. */
export function oneLine(text: string, max = 140): string {
  const flat = text
    .split("\n")
    .map((l) => l.replace(/^\s*[-*•]\s*/, "").trim())
    .filter(Boolean)
    .join(" · ")
    .replace(/^[^·]{0,24}:\s*·\s*/, "");
  return flat.length > max ? `${flat.slice(0, max - 1).trimEnd()}…` : flat;
}

function finish(run: Run) {
  if (run.status !== "error") run.status = "done";
  for (const s of run.stages) if (s.status === "running") s.status = "done";
}

/* ── Summaries ───────────────────────────────────────────────────────── */

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export function isFailure(step: Step): boolean {
  return step.tone === "danger";
}

/** Passing checks are folded into one "N checks passed" row. */
export function isFoldedPass(step: Step): boolean {
  return step.check && step.status === "passed";
}

interface Counts {
  reads: number;
  lookups: number;
  checks: number;
  failed: number;
  skipped: number;
  understood: number; // the Copilot read the request
  recognised: number; // the Copilot recognised the case / rules named
  asked: number; // the language model answered
  other: number;
}

export function countSteps(steps: Step[]): Counts {
  const c: Counts = { reads: 0, lookups: 0, checks: 0, failed: 0, skipped: 0,
                      understood: 0, recognised: 0, asked: 0, other: 0 };
  for (const s of steps) {
    if (READ_KINDS.has(s.kind)) c.reads += 1;
    else if (LOOKUP_KINDS.has(s.kind)) c.lookups += 1;
    else if (s.check || s.kind === "rule_check") c.checks += 1;
    else if (s.kind === "intent") c.understood += 1;
    else if (s.kind === "entities") c.recognised += 1;
    else if (s.kind === "llm_call" && s.status === "ok") c.asked += 1;
    else c.other += 1;
    if (isFailure(s)) c.failed += 1;
    if (s.status === "skipped" && s.kind === "rule_check") c.skipped += 1;
  }
  return c;
}

/** What the steps did, most telling first, each with how many steps it covers. */
function phrases(c: Counts): [string, number][] {
  const out: [string, number][] = [];
  if (c.reads) out.push([`read ${plural(c.reads, "document")}`, c.reads]);
  if (c.checks) out.push([`ran ${plural(c.checks, "check")}`, c.checks]);
  if (c.understood) out.push(["understood the request", c.understood]);
  if (c.lookups) out.push([`made ${plural(c.lookups, "Knowledge Graph lookup")}`, c.lookups]);
  if (c.recognised) out.push(["recognised the context", c.recognised]);
  if (c.asked) out.push(["asked the language model", c.asked]);
  return out;
}

/** "evaluated 12 checks, 2 failed" — the text after a stage's name. */
export function stageSummary(stage: Stage): string {
  const c = countSteps(stage.steps);
  const parts: string[] = [];
  if (c.reads) parts.push(`read ${plural(c.reads, "document")}`);
  if (c.checks) parts.push(`evaluated ${plural(c.checks, "check")}`);
  if (c.lookups && !c.checks) parts.push(plural(c.lookups, "Knowledge Graph lookup"));
  if (!parts.length) {
    const p = phrases(c);
    if (p.length) parts.push(p[0][0]);
    else if (c.other) parts.push(plural(c.other, "step"));
  }
  if (c.failed) parts.push(`${c.failed} failed`);
  if (c.skipped) parts.push(`${c.skipped} skipped`);
  return parts.join(", ");
}

/** "Read 3 documents, ran 24 checks, and 14 more steps" — a run's collapsed headline. */
export function runHeadline(run: Run): string {
  const steps = run.stages.flatMap((s) => s.steps);
  const shownPhrases = phrases(countSteps(steps)).slice(0, 2);
  const parts = shownPhrases.map(([text]) => text);
  const rest = steps.length - shownPhrases.reduce((n, [, k]) => n + k, 0);
  if (rest > 0) parts.push(parts.length ? `and ${plural(rest, "more step")}` : plural(rest, "step"));
  if (!parts.length) return run.status === "running" ? "Thinking…" : "No steps recorded";
  const text = parts.length > 2
    ? `${parts.slice(0, -1).join(", ")}, ${parts.at(-1)}`
    : parts.join(parts[1]?.startsWith("and ") ? " " : " and ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function runTitle(run: Run): string {
  if (run.kind === "copilot") {
    const q = run.question.trim();
    return q ? `“${q.length > 70 ? `${q.slice(0, 70)}…` : q}”` : "Copilot request";
  }
  return `Audit of ${run.caseId}${run.version ? ` · v${run.version}` : ""}`;
}

/** The step to show next to the spinner while a run is working. */
export function currentActivity(run: Run): string {
  const stage = [...run.stages].reverse().find((s) => s.status === "running") ?? run.stages.at(-1);
  if (!stage) return "Starting…";
  const last = stage.steps.at(-1);
  return last ? `${stage.label} · ${last.verb} ${last.target}`.trim() : `${stage.label}…`;
}

export function formatDuration(ms: number | null): string {
  if (ms == null) return "";
  if (ms < 1) return "<1 ms";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}
