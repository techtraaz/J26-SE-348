import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, ExternalLink, FileText, Loader2, Minus, Network, RotateCw, X } from "lucide-react";
import clsx from "clsx";
import { ApiError, c2 } from "@/lib/apiClient";
import { Button } from "@/features/extraction/components/Button";
import { EmptyState } from "@/features/extraction/components/EmptyState";
import { ProgressBar } from "@/features/extraction/components/ProgressBar";
import { formatBytes, formatDuration, formatRelativeTime } from "@/features/extraction/format";
import type { KgChanges, Policy, PolicyRun, Totals } from "@/types/policies";
import { KG_KINDS, STEPS, isActive, runKey, stepStates, type StepState } from "./stages";
import { KG_COLORS } from "./graphLayout";
import { KgChangeGraph } from "./KgChangeGraph";

export function PolicyDetail({ policy }: { policy: Policy }) {
  const qc = useQueryClient();
  const runQ = useQuery({
    queryKey: runKey(policy.name),
    queryFn: () => c2.run(policy.name),
    retry: false,
    refetchInterval: (q) => (isActive(q.state.data) ? 1200 : false),
  });
  const run = runQ.data ?? null;
  const notYet = runQ.error instanceof ApiError && runQ.error.status === 404;

  // the list shows each policy's status; refresh it once a run ends
  const status = run?.status;
  useEffect(() => {
    if (status === "done" || status === "failed") void qc.invalidateQueries({ queryKey: ["c2", "policies"] });
  }, [status, qc]);

  const rerun = useMutation({
    mutationFn: (code?: string) => c2.reingest(policy.name, code),
    onSuccess: (job) => {
      qc.setQueryData(runKey(policy.name), job);
      void qc.invalidateQueries({ queryKey: ["c2"] });
    },
  });
  const busy = isActive(run) || rerun.isPending;

  return (
    <div className="flex min-w-0 flex-col gap-5">
      {/* ── The file ── */}
      <section className="flex flex-wrap items-center gap-4 rounded-2xl border border-line bg-surface px-5 py-4 shadow-sm">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-surface-muted text-primary">
          <FileText size={22} strokeWidth={1.7} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[17px] font-semibold text-ink-h" title={policy.name}>{policy.name}</h2>
          <p className="text-[13px] text-ink-muted">
            {formatBytes(policy.size_bytes)} · stored {formatRelativeTime(policy.uploaded_at)}
            {run?.code && <> · <code className="text-[12px]">{run.code}</code></>}
          </p>
        </div>
        <div className="flex gap-2">
          <a href={c2.fileUrl(policy.name)} target="_blank" rel="noreferrer"
             className="inline-flex h-9 items-center gap-2 rounded-full border border-line bg-surface px-4 text-[13px] font-medium text-ink-h hover:bg-surface-muted">
            <ExternalLink size={15} /> Open PDF
          </a>
          <Button variant="primary" disabled={busy || runQ.isLoading} onClick={() => rerun.mutate(undefined)}>
            <RotateCw size={15} className={clsx(busy && "animate-spin")} />
            {notYet ? "Add to graph" : "Run again"}
          </Button>
        </div>
        {rerun.error && <p className="w-full text-[13px] text-danger">{rerun.error.message}</p>}
      </section>

      {runQ.isLoading && <p className="text-[13px] text-ink-muted">Loading…</p>}
      {runQ.error && !notYet && <p className="text-[13px] text-danger">{runQ.error.message}</p>}
      {notYet && !rerun.isPending && (
        <EmptyState icon={<Network size={22} />} title="Not in the knowledge graph yet"
                    description="The file is stored but has not been added to the graph. Press “Add to graph” to run the update." />
      )}

      {run && (
        <>
          <RunProgress run={run} onRerun={(code) => rerun.mutate(code)} busy={busy} />
          {run.status === "done" && run.changes && KG_KINDS.includes(run.kind ?? "") && (
            <Changes run={run} changes={run.changes} title={policy.name} />
          )}
        </>
      )}
    </div>
  );
}

const STEP_ICON: Record<StepState, React.ReactNode> = {
  done: <Check size={14} strokeWidth={2.6} />,
  running: <Loader2 size={14} strokeWidth={2.4} className="animate-spin" />,
  pending: null,
  failed: <X size={14} strokeWidth={2.6} />,
  skipped: <Minus size={14} strokeWidth={2.4} />,
  warning: <AlertTriangle size={13} strokeWidth={2.4} />,
};

const STEP_STYLE: Record<StepState, string> = {
  done: "bg-success text-white border-success",
  running: "bg-info text-white border-info",
  pending: "bg-surface text-ink-soft border-line",
  failed: "bg-danger text-white border-danger",
  skipped: "bg-surface-muted text-ink-soft border-line",
  warning: "bg-warning text-white border-warning",
};

function RunProgress({ run, onRerun, busy }: { run: PolicyRun; onRerun: (code?: string) => void; busy: boolean }) {
  const states = stepStates(run);
  const s = run.summary;
  const took = run.started_at && run.finished_at
    ? formatDuration(new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) : null;
  const skippedKind = run.status === "done" && run.kind && !KG_KINDS.includes(run.kind);

  return (
    <section className="rounded-2xl border border-line bg-surface px-5 py-4 shadow-sm" aria-label="Knowledge graph update">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[15px] font-semibold text-ink-h">Knowledge graph update</h3>
        <span className="text-[12px] text-ink-soft">
          {isActive(run) ? "running…" : run.finished_at ? `finished ${formatRelativeTime(run.finished_at)}` : ""}
          {took && ` · took ${took}`}
        </span>
      </div>

      <ol className="grid grid-cols-2 gap-x-3 gap-y-4 sm:grid-cols-4 xl:grid-cols-8">
        {STEPS.map((step) => {
          const st = states[step.id];
          const extracting = step.id === "extract" && st === "running" && run.progress?.total;
          return (
            <li key={step.id} className="min-w-0" aria-current={st === "running" ? "step" : undefined}>
              <div className="flex items-center gap-2">
                <span className={clsx("flex size-6 shrink-0 items-center justify-center rounded-full border text-[11px]", STEP_STYLE[st])}>
                  {STEP_ICON[st]}
                </span>
                <span className={clsx("truncate text-[13px] font-medium", st === "pending" || st === "skipped" ? "text-ink-soft" : "text-ink-h")}>
                  {step.label}
                </span>
              </div>
              <p className="mt-1 text-[11.5px] leading-snug text-ink-soft">
                {extracting ? `${run.progress!.done} of ${run.progress!.total} paragraphs` : step.hint}
              </p>
              {extracting && (
                <div className="mt-1.5"><ProgressBar value={run.progress!.done / run.progress!.total} label="LLM extraction" /></div>
              )}
            </li>
          );
        })}
      </ol>

      {run.status === "failed" && (
        <Notice tone="danger" title="The update failed">{run.error}</Notice>
      )}
      {s?.llm_unavailable && (
        <Notice tone="warning" title="LLM offline: nothing was extracted">
          The paragraphs were added to the graph, but no requirements, definitions or equations
          ({s.llm_errors} paragraph(s) not read). Start the LLM server and press “Run again”.
          <span className="mt-1 block text-[12px] opacity-80">{s.llm_unavailable}</span>
        </Notice>
      )}
      {s && !s.llm_unavailable && s.llm_errors > 0 && (
        <Notice tone="warning" title={`${s.llm_errors} paragraph(s) could not be read by the LLM`}>
          The rest were added. Running again retries them.
        </Notice>
      )}
      {s && s.plan_errors.length > 0 && (
        <Notice tone="warning" title="Some changes were not written">
          <ul className="list-disc pl-4">{s.plan_errors.slice(0, 5).map((e) => <li key={e}>{e}</li>)}</ul>
        </Notice>
      )}
      {skippedKind && <CodeNotice kind={run.kind!} onRerun={onRerun} busy={busy} />}
    </section>
  );
}

function CodeNotice({ kind, onRerun, busy }: { kind: string; onRerun: (code?: string) => void; busy: boolean }) {
  const [code, setCode] = useState("");
  return (
    <Notice tone="info" title="Not added to the graph">
      The document was read as “{kind.replace("_", " ")}”. Only standards, amendments and Acts are added.
      If it is a standard, give its code and run again.
      <form className="mt-2 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (code.trim()) onRerun(code.trim()); }}>
        <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="e.g. LKAS 18" aria-label="Standard code"
               className="h-8 w-40 rounded-full border border-line bg-input px-3 text-[13px] text-ink-h outline-none focus:border-primary" />
        <Button type="submit" size="sm" variant="primary" disabled={busy || !code.trim()}>Run with this code</Button>
      </form>
    </Notice>
  );
}

const NOTICE_TONE = {
  danger: "border-danger/40 bg-danger/8 text-danger",
  warning: "border-warning/40 bg-warning/10 text-ink",
  info: "border-info/30 bg-info/8 text-ink",
} as const;

function Notice({ tone, title, children }: { tone: keyof typeof NOTICE_TONE; title: string; children?: React.ReactNode }) {
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={clsx("mt-4 rounded-xl border px-4 py-3 text-[13px]", NOTICE_TONE[tone])}>
      <p className="font-semibold text-ink-h">{title}</p>
      {children && <div className="mt-0.5">{children}</div>}
    </div>
  );
}

// ── What changed ──

const TYPES = [
  { label: "Requirement", plural: "Requirements" },
  { label: "Definition", plural: "Definitions" },
  { label: "Equation", plural: "Equations" },
  { label: "Section", plural: "Paragraphs" },
  { label: "Standard", plural: "Standard" },
];

function Changes({ run, changes, title }: { run: PolicyRun; changes: KgChanges; title: string }) {
  const s = run.summary!;
  const before = run.totals?.before ?? null;
  const after = run.totals?.after ?? null;
  return (
    <section className="rounded-2xl border border-line bg-surface px-5 py-4 shadow-sm" aria-label="What changed in the knowledge graph">
      <h3 className="text-[15px] font-semibold text-ink-h">What changed in the knowledge graph</h3>
      <p className="mt-0.5 text-[13px] text-ink-muted">
        {s.chunks} paragraph(s) read, {s.sent_to_llm} sent to the LLM, {s.written} item(s) merged into the graph.
      </p>

      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <TotalTile name="Nodes" field="nodes" before={before} after={after} />
        <TotalTile name="Relationships" field="relationships" before={before} after={after} />
        <CountTile name="Requirements" created={s.created.Requirement ?? 0} matched={s.matched.Requirement ?? 0} />
        <CountTile name="Definitions · Equations" created={(s.created.Definition ?? 0) + (s.created.Equation ?? 0)}
                   matched={(s.matched.Definition ?? 0) + (s.matched.Equation ?? 0)} />
      </div>

      <div className="mt-5 grid gap-6 2xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div className="min-w-0">
          <KgChangeGraph graph={changes.graph} title={title} />
        </div>
        <div className="min-w-0">
          <TypeTable created={s.created} matched={s.matched} />
          <NewItems changes={changes} />
        </div>
      </div>
    </section>
  );
}

function TotalTile({ name, field, before, after }: { name: string; field: keyof Totals; before: Totals | null; after: Totals | null }) {
  const delta = before && after ? after[field] - before[field] : null;
  return (
    <div className="rounded-xl border border-line-light bg-surface-muted/50 px-3.5 py-3">
      <p className="text-[12px] text-ink-muted">{name} in the graph</p>
      {after ? (
        <>
          <p className="num mt-0.5 text-[20px] font-semibold text-ink-h">{after[field].toLocaleString()}</p>
          <p className="num text-[12px] text-ink-soft">
            {before && <>{before[field].toLocaleString()} before · </>}
            {delta !== null && <span className={delta > 0 ? "font-semibold text-success" : ""}>{delta >= 0 ? `+${delta}` : delta}</span>}
          </p>
        </>
      ) : (
        <p className="mt-1 text-[12px] text-ink-soft">not counted</p>
      )}
    </div>
  );
}

function CountTile({ name, created, matched }: { name: string; created: number; matched: number }) {
  return (
    <div className="rounded-xl border border-line-light bg-surface-muted/50 px-3.5 py-3">
      <p className="text-[12px] text-ink-muted">{name}</p>
      <p className="num mt-0.5 text-[20px] font-semibold text-ink-h">{created} <span className="text-[13px] font-normal text-ink-muted">new</span></p>
      <p className="num text-[12px] text-ink-soft">{matched} matched existing</p>
    </div>
  );
}

function TypeTable({ created, matched }: { created: Record<string, number>; matched: Record<string, number> }) {
  const rows = [...TYPES, { label: "SourceChunk", plural: "Source text chunks" }]
    .filter((t) => created[t.label] || matched[t.label]);
  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className="border-b border-line-light text-left text-[12px] text-ink-muted">
          <th className="py-1.5 font-medium">Type</th>
          <th className="py-1.5 text-right font-medium">New</th>
          <th className="py-1.5 text-right font-medium">Matched</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((t) => (
          <tr key={t.label} className="border-b border-line-light last:border-0">
            <td className="py-1.5 text-ink-h">
              <span className="mr-2 inline-block size-2 rounded-full" style={{ background: KG_COLORS[t.label] ?? "var(--kg-other)" }} aria-hidden />
              {t.plural}
            </td>
            <td className="num py-1.5 text-right font-semibold text-ink-h">{created[t.label] ?? 0}</td>
            <td className="num py-1.5 text-right text-ink-muted">{matched[t.label] ?? 0}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const PAGE = 40;

function NewItems({ changes }: { changes: KgChanges }) {
  const tabs = TYPES.filter((t) => changes.new[t.label]?.length);
  const [picked, setPicked] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [all, setAll] = useState(false);
  if (!tabs.length) return <p className="mt-4 text-[13px] text-ink-muted">Nothing new: everything in this document was already in the graph.</p>;

  const tab = tabs.find((t) => t.label === picked) ?? tabs[0];
  const q = query.trim().toLowerCase();
  const items = (changes.new[tab.label] ?? []).filter((i) => !q || `${i.key} ${i.caption}`.toLowerCase().includes(q));
  return (
    <div className="mt-5">
      <h4 className="text-[13px] font-semibold text-ink-h">New in the graph</h4>
      <div role="tablist" aria-label="New nodes by type" className="mt-2 flex flex-wrap gap-1.5">
        {tabs.map((t) => (
          <button key={t.label} type="button" role="tab" aria-selected={t.label === tab.label}
                  onClick={() => { setPicked(t.label); setAll(false); }}
                  className={clsx("rounded-full border px-3 py-1 text-[12.5px]",
                    t.label === tab.label ? "border-primary bg-primary text-white" : "border-line bg-surface text-ink-h hover:bg-surface-muted")}>
            {t.plural} <span className="num opacity-75">{changes.new[t.label].length}</span>
          </button>
        ))}
      </div>
      <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter" aria-label="Filter new nodes"
             className="mt-2.5 h-8 w-full rounded-full border border-line bg-input px-3 text-[13px] text-ink-h outline-none focus:border-primary" />
      <ul className="thin-scroll mt-2 max-h-[420px] overflow-y-auto pr-1">
        {(all ? items : items.slice(0, PAGE)).map((i) => (
          <li key={i.key} className="border-b border-line-light py-2 last:border-0">
            <code className="text-[11.5px] text-ink-muted">{i.key}</code>
            <p className="text-[13px] text-ink">{i.caption}</p>
          </li>
        ))}
      </ul>
      {!all && items.length > PAGE && (
        <Button size="sm" variant="ghost" onClick={() => setAll(true)}>Show all {items.length}</Button>
      )}
    </div>
  );
}
