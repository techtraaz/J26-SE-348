import { useMemo, useState } from "react";
import { ArrowRight, Check, ChevronDown, ChevronRight, CircleAlert, CircleCheck, CircleX, LoaderCircle,
         Sparkles, X } from "lucide-react";
import {
  buildRuns,
  currentActivity,
  formatDuration,
  isFailure,
  isFoldedPass,
  runHeadline,
  runTitle,
  stageSummary,
  type Review,
  type Run,
  type Stage,
  type Status,
  type Step,
  type Tone,
  type Verdict,
  type XaiEvent,
} from "./timeline";

// A Claude-style "thinking" dropdown per run: one collapsible block for each
// audit or Copilot turn, stages (agents) inside it, steps inside each stage.
// Failed checks are red; passing checks fold into one "N checks passed" row;
// any row with facts opens to show the exact values compared.

const font: React.CSSProperties = { fontFamily: "'Inter Variable', system-ui, -apple-system, sans-serif" };
const mono: React.CSSProperties = { fontFamily: "'JetBrains Mono Variable', monospace" };

const toneColor: Record<Tone, string> = {
  danger: "var(--danger)",
  warning: "var(--warning)",
  success: "var(--success)",
  muted: "var(--text-soft)",
  neutral: "var(--text-muted)",
};

export function ThinkingTimeline({ events, connected, streamId }: {
  events: XaiEvent[];
  connected: boolean;
  streamId: string;
}) {
  const runs = useMemo(() => buildRuns(events), [events]);

  if (runs.length === 0) {
    return (
      <div style={{ textAlign: "center", padding: "48px 20px", color: "var(--text-soft)", ...font }}>
        <Sparkles size={26} strokeWidth={1.2} color="var(--border)" style={{ marginBottom: 14 }} />
        <p style={{ fontSize: 13, lineHeight: 1.6 }}>
          {connected ? "Run an audit or ask the Copilot to see its reasoning here." : "Connecting to the reasoning stream…"}
        </p>
        <p style={{ fontSize: 11, marginTop: 8, ...mono }}>{streamId}</p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      {runs.map((run, i) => (
        <RunBlock key={run.key} run={run} latest={i === runs.length - 1} />
      ))}
    </div>
  );
}

/* ── Run: the dropdown ─────────────────────────────────────────────── */

function RunBlock({ run, latest }: { run: Run; latest: boolean }) {
  const [open, setOpen] = useState<boolean | null>(null);
  const expanded = open ?? (latest || run.status === "running");
  const failed = run.stages.reduce((n, s) => n + s.steps.filter(isFailure).length, 0);
  const running = run.status === "running";

  return (
    <section aria-label={runTitle(run)} style={font}>
      <div style={{ fontSize: 11, color: "var(--text-soft)", marginBottom: 4, display: "flex", gap: 6 }}>
        <span style={{ textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 600 }}>
          {run.kind === "copilot" ? "Copilot" : "Audit"}
        </span>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{runTitle(run)}</span>
      </div>

      <button
        type="button"
        className="xai-headline"
        aria-expanded={expanded}
        onClick={() => setOpen(!expanded)}
        style={{
          ...font, display: "flex", alignItems: "center", gap: 6, width: "100%", textAlign: "left",
          background: "none", border: "none", padding: "2px 0", cursor: "pointer",
          fontSize: 13.5, color: "var(--text)",
        }}
      >
        {running && <LoaderCircle size={14} className="xai-spin" color="var(--text-muted)" />}
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 }}>
          {running ? currentActivity(run) : runHeadline(run)}
        </span>
        {failed > 0 && (
          <span style={{ color: "var(--danger)", fontSize: 12, whiteSpace: "nowrap" }}>· {failed} failed</span>
        )}
        {!expanded && run.review?.verdict && <VerdictChip verdict={run.review.verdict} kind={run.kind} small />}
        {expanded ? <ChevronDown size={14} style={{ flexShrink: 0 }} /> : <ChevronRight size={14} style={{ flexShrink: 0 }} />}
      </button>

      {expanded && (
        <div style={{
          marginTop: 8, border: "1px solid var(--border-strong)", borderRadius: "var(--radius)",
          background: "var(--surface)", overflow: "hidden",
        }}>
          {run.stages.length === 0 && <Row muted>Starting…</Row>}
          {run.stages.map((stage) => <StageRow key={stage.id} stage={stage} />)}
          {run.review && <ReviewCard review={run.review} kind={run.kind} />}
          <RunFooter run={run} />
        </div>
      )}

    </section>
  );
}

function RunFooter({ run }: { run: Run }) {
  if (run.status === "running") return null;
  const parts: string[] = [];
  if (run.kind === "audit") {
    parts.push(run.status === "error" ? "Stopped with an error" : "Audit complete");
    if (run.totalFindings != null) parts.push(`${run.totalFindings} finding${run.totalFindings === 1 ? "" : "s"}`);
  } else {
    parts.push(run.status === "error" ? "Stopped with an error" : "Answered");
    if (run.durationMs != null) parts.push(formatDuration(run.durationMs));
  }
  return (
    <div style={{ padding: "8px 14px", fontSize: 12, color: "var(--text-muted)", background: "var(--surface-muted)",
                  borderTop: "1px solid var(--border-light)" }}>
      {parts.join(" · ")}
      {run.answer && (
        <div style={{ marginTop: 3, color: "var(--text-soft)", overflow: "hidden", textOverflow: "ellipsis",
                      whiteSpace: "nowrap" }}>
          {run.answer}
        </div>
      )}
    </div>
  );
}

/* ── Review Agent: verdict, summary, next steps ────────────────────── */

const VERDICTS: Record<Verdict, { label: string; color: string; Icon: typeof CircleCheck }> = {
  clear: { label: "All clear", color: "var(--success)", Icon: CircleCheck },
  review: { label: "Needs confirmation", color: "var(--warning)", Icon: CircleAlert },
  action_required: { label: "Action needed", color: "var(--danger)", Icon: CircleX },
};

// A chat turn is "answered" rather than "all clear".
const CHAT_LABELS: Partial<Record<Verdict, string>> = { clear: "Answered", review: "Needs attention" };

function verdictLabel(verdict: Verdict, kind: Run["kind"]): string {
  return (kind === "copilot" && CHAT_LABELS[verdict]) || VERDICTS[verdict].label;
}

function VerdictChip({ verdict, kind, small }: { verdict: Verdict; kind: Run["kind"]; small?: boolean }) {
  const { color, Icon } = VERDICTS[verdict];
  const label = verdictLabel(verdict, kind);
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4, flexShrink: 0, whiteSpace: "nowrap",
      fontSize: small ? 11 : 11.5, fontWeight: 600, color, padding: small ? "1px 7px" : "2px 8px",
      borderRadius: "var(--radius-pill)", background: `color-mix(in srgb, ${color} 12%, transparent)`,
    }}>
      <Icon size={small ? 11 : 12} strokeWidth={2} /> {label}
    </span>
  );
}

function ReviewCard({ review, kind }: { review: Review; kind: Run["kind"] }) {
  const chat = kind === "copilot";
  // the headline only adds something when it says more than the chip
  const showHeadline = review.verdict ? review.headline !== verdictLabel(review.verdict, kind) : true;
  return (
    <div aria-label="Review agent" style={{
      borderTop: "1px solid var(--border-light)", padding: "12px 14px 12px",
      background: "color-mix(in srgb, var(--surface-muted) 45%, var(--surface))",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: review.pending ? 0 : 8 }}>
        <Sparkles size={13} color="var(--text-muted)" />
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.05em", textTransform: "uppercase",
                       color: "var(--text-soft)", flex: 1 }}>
          Review agent
        </span>
        {review.verdict && <VerdictChip verdict={review.verdict} kind={kind} />}
      </div>

      {review.pending ? (
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8, fontSize: 12.5,
                      color: "var(--text-muted)" }}>
          <LoaderCircle size={13} className="xai-spin" />
          {chat ? "Reading the trace and writing a wrap-up…" : "Reading the trace and writing a summary…"}
        </div>
      ) : (
        <>
          {review.headline && showHeadline && (
            <p style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text-h)", marginBottom: 4 }}>{review.headline}</p>
          )}
          {review.summary && (
            <p style={{ fontSize: 13, lineHeight: 1.55, color: "var(--text)" }}>{review.summary}</p>
          )}
          {review.nextSteps.length > 0 && (
            <>
              <p style={{ fontSize: 11.5, fontWeight: 600, color: "var(--text-muted)", margin: "10px 0 4px" }}>
                Next steps
              </p>
              <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 4 }}>
                {review.nextSteps.map((step, i) => (
                  <li key={i} style={{ display: "flex", gap: 6, fontSize: 12.5, lineHeight: 1.45, color: "var(--text)" }}>
                    <ArrowRight size={12} style={{ marginTop: 3, flexShrink: 0 }} color="var(--text-soft)" />
                    <span>{step}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          <p style={{ fontSize: 11, color: "var(--text-soft)", marginTop: 10 }}>
            {review.source === "rules"
              ? "Written from the trace with fixed wording (language model unavailable)."
              : `${chat ? "Wrap-up" : "Summary"} written by the review agent from the trace above${review.model ? ` · ${review.model}` : ""}. ${chat ? "The verdict comes from the trace." : "Verdict and next steps come from the checks."}`}
          </p>
        </>
      )}
    </div>
  );
}

/* ── Stage: one agent ──────────────────────────────────────────────── */

function StatusIcon({ status, failed }: { status: Status; failed?: boolean }) {
  if (status === "running") return <LoaderCircle size={14} className="xai-spin" color="var(--text-muted)" />;
  if (status === "error" || failed) return <X size={14} color="var(--danger)" />;
  return <Check size={14} color="var(--success)" />;
}

function StageRow({ stage }: { stage: Stage }) {
  const failures = stage.steps.filter(isFailure).length;
  const [open, setOpen] = useState<boolean | null>(null);
  const expanded = open ?? (stage.status === "running" || failures > 0);
  const summary = stageSummary(stage);
  const shown = stage.steps.filter((s) => !isFoldedPass(s));
  const passed = stage.steps.filter(isFoldedPass);

  return (
    <div style={{ borderTop: "1px solid var(--border-light)", marginTop: -1 }}>
      <button
        type="button"
        className="xai-row"
        aria-expanded={expanded}
        onClick={() => setOpen(!expanded)}
        style={{ ...rowButton, padding: "10px 14px" }}
      >
        <span style={{ display: "flex", width: 16, flexShrink: 0 }}>
          <StatusIcon status={stage.status} failed={stage.status === "done" && failures > 0} />
        </span>
        <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          <span style={{ color: "var(--text-h)", fontWeight: 500 }}>{stage.label}</span>
          {summary && <span style={{ color: "var(--text-muted)" }}> · {summary}</span>}
        </span>
        {stage.durationMs != null && (
          <span style={{ fontSize: 11, color: "var(--text-soft)", ...mono }}>{formatDuration(stage.durationMs)}</span>
        )}
        {expanded ? <ChevronDown size={13} color="var(--text-soft)" /> : <ChevronRight size={13} color="var(--text-soft)" />}
      </button>

      {expanded && (
        <div style={{ margin: "0 14px 10px 21px", borderLeft: "1px solid var(--border)", paddingLeft: 10 }}>
          {shown.map((step) => <StepRow key={step.id} step={step} />)}
          {passed.length > 0 && <PassedGroup steps={passed} />}
          {stage.steps.length === 0 && stage.status === "running" && <Row muted>Working…</Row>}
          {stage.note && stage.status !== "running" && (
            <p style={{ fontSize: 11.5, color: "var(--text-soft)", padding: "6px 4px 2px", lineHeight: 1.45 }}>
              {stage.note}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Steps ─────────────────────────────────────────────────────────── */

const rowButton: React.CSSProperties = {
  ...font, display: "flex", alignItems: "center", gap: 8, width: "100%", textAlign: "left",
  background: "none", border: "none", cursor: "pointer", fontSize: 13, color: "var(--text)",
  borderRadius: 6,
};

function StepRow({ step }: { step: Step }) {
  const [open, setOpen] = useState(false);
  const failed = isFailure(step);
  const color = failed ? "var(--danger)" : undefined;
  const hasFacts = step.facts.length > 0;

  return (
    <div className={failed ? "xai-step xai-step-failed" : "xai-step"} style={{ borderRadius: 6, margin: "1px 0" }}>
      <button
        type="button"
        className="xai-row"
        aria-expanded={hasFacts ? open : undefined}
        disabled={!hasFacts}
        onClick={() => setOpen(!open)}
        style={{ ...rowButton, alignItems: "flex-start", padding: "5px 6px", cursor: hasFacts ? "pointer" : "default" }}
      >
        <span style={{ flex: 1, minWidth: 0 }}>
          <span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            <span style={{ color: color ?? toneColor[step.tone === "success" ? "neutral" : step.tone] }}>{step.verb}</span>{" "}
            <span style={{ color: color ?? "var(--text-h)", fontWeight: 500 }}>{step.target}</span>
          </span>
          {step.detail && (
            <span style={{
              display: "-webkit-box", WebkitLineClamp: open ? undefined : 2, WebkitBoxOrient: "vertical",
              overflow: "hidden", fontSize: 12, lineHeight: 1.45, marginTop: 1,
              color: failed ? "var(--danger)" : "var(--text-muted)", opacity: failed ? 0.9 : 1,
            }}>
              {step.detail}
            </span>
          )}
        </span>
        {hasFacts && (open
          ? <ChevronDown size={13} color="var(--text-soft)" style={{ marginTop: 3, flexShrink: 0 }} />
          : <ChevronRight size={13} color="var(--text-soft)" style={{ marginTop: 3, flexShrink: 0 }} />)}
      </button>
      {open && hasFacts && <Facts step={step} />}
    </div>
  );
}

function Facts({ step }: { step: Step }) {
  return (
    <dl style={{
      display: "grid", gridTemplateColumns: "minmax(80px, max-content) 1fr", columnGap: 12, rowGap: 4,
      margin: "2px 6px 8px", padding: "8px 10px", borderRadius: 6, fontSize: 11.5,
      background: "var(--surface-muted)", border: "1px solid var(--border-light)",
    }}>
      {step.facts.map((f, i) => (
        <div key={`${f.label}-${i}`} style={{ display: "contents" }}>
          <dt style={{ color: "var(--text-muted)" }}>{f.label}</dt>
          <dd style={{ color: "var(--text-h)", wordBreak: "break-word", ...mono }}>{f.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function PassedGroup({ steps }: { steps: Step[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ margin: "1px 0" }}>
      <button
        type="button"
        className="xai-row"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        style={{ ...rowButton, padding: "5px 6px" }}
      >
        <Check size={13} color="var(--success)" />
        <span style={{ flex: 1, color: "var(--text-muted)" }}>
          {steps.length} {steps.length === 1 ? "check" : "checks"} passed
        </span>
        {open ? <ChevronDown size={13} color="var(--text-soft)" /> : <ChevronRight size={13} color="var(--text-soft)" />}
      </button>
      {open && (
        <div style={{ paddingLeft: 12 }}>
          {steps.map((s) => <StepRow key={s.id} step={s} />)}
        </div>
      )}
    </div>
  );
}

function Row({ children, muted }: { children: React.ReactNode; muted?: boolean }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 14px", fontSize: 12.5,
                  color: muted ? "var(--text-soft)" : "var(--text)" }}>
      {muted && <LoaderCircle size={12} className="xai-spin" />}
      {children}
    </div>
  );
}
