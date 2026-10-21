import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useDropzone } from "react-dropzone";
import { FileText, FileUp, PlugZap, X } from "lucide-react";
import clsx from "clsx";
import { useSearchParams } from "react-router-dom";
import { ApiError, c2 } from "@/lib/apiClient";
import { env } from "@/config/env";
import { Button } from "@/features/extraction/components/Button";
import { EmptyState } from "@/features/extraction/components/EmptyState";
import { ProgressBar } from "@/features/extraction/components/ProgressBar";
import { formatBytes, formatRelativeTime } from "@/features/extraction/format";
import type { Policy } from "@/types/policies";
import { isActive, runKey, runLine } from "./stages";
import { PolicyDetail } from "./PolicyDetail";

// Policies tab (Component-02): standards and policy PDFs kept in object storage. Each upload
// is added to the knowledge graph, and the page shows the update live and what it changed.

const TONE: Record<ReturnType<typeof runLine>["tone"], string> = {
  info: "text-info",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
  muted: "text-ink-soft",
};

export function PoliciesPage() {
  const [params, setParams] = useSearchParams();
  const list = useQuery({
    queryKey: ["c2", "policies"],
    queryFn: c2.policies,
    retry: 1,
    refetchInterval: (q) => (q.state.data?.some((p) => isActive(p.last_run)) ? 2500 : false),
  });
  const policies = list.data ?? [];
  const selectedName = params.get("p") ?? policies[0]?.name ?? null;
  const selected = policies.find((p) => p.name === selectedName) ?? null;
  const select = (name: string) => setParams({ p: name }, { replace: true });

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <header className="px-8 pb-6 pt-10">
        <h1 className="heading-serif text-[40px] leading-[1.1]">Policies</h1>
        <p className="mt-1.5 text-[15px] text-ink-muted">
          Upload standards and policy documents. Each is stored and added to the audit knowledge graph.
        </p>
      </header>

      <div className="grid min-w-0 gap-6 px-8 pb-12 lg:grid-cols-[340px_minmax(0,1fr)]">
        <aside className="flex min-w-0 flex-col gap-4">
          <Uploader onUploaded={select} />
          <section aria-label="Stored policies" className="rounded-2xl border border-line bg-surface p-2 shadow-sm">
            <h2 className="px-3 pb-1 pt-2 text-[12px] font-semibold uppercase tracking-wide text-ink-muted">
              Stored policies {policies.length > 0 && <span className="num">· {policies.length}</span>}
            </h2>
            {list.isLoading && <p className="px-3 py-4 text-[13px] text-ink-muted">Loading…</p>}
            {list.error && (
              <p className="px-3 py-4 text-[13px] text-danger">{list.error.message}</p>
            )}
            {!list.isLoading && !list.error && policies.length === 0 && (
              <p className="px-3 py-4 text-[13px] text-ink-muted">Nothing uploaded yet.</p>
            )}
            <ul>
              {policies.map((p) => (
                <PolicyRow key={p.name} policy={p} active={p.name === selected?.name} onClick={() => select(p.name)} />
              ))}
            </ul>
          </section>
        </aside>

        <div className="min-w-0">
          {selected ? (
            <PolicyDetail key={selected.name} policy={selected} />
          ) : list.error ? (
            <EmptyState icon={<PlugZap size={22} />} title="Policies are unavailable"
                        description={list.error instanceof ApiError && list.error.status > 0 ? list.error.message
                          : `Start Component 02 on ${env.c2Base} (uvicorn app.main:app --port 8002).`} />
          ) : (
            !list.isLoading && (
              <EmptyState icon={<FileUp size={22} />} title="Upload a policy to start"
                          description="Drop a PDF on the left. It is stored, then its paragraphs, requirements, definitions and equations are added to the knowledge graph." />
            )
          )}
        </div>
      </div>
    </div>
  );
}

function PolicyRow({ policy, active, onClick }: { policy: Policy; active: boolean; onClick: () => void }) {
  const line = runLine(policy.last_run);
  const run = policy.last_run;
  return (
    <li>
      <button type="button" onClick={onClick} aria-current={active ? "true" : undefined}
              className={clsx("flex w-full items-start gap-3 rounded-xl px-3 py-2.5 text-left transition-colors",
                active ? "bg-[var(--sidebar-active)]" : "hover:bg-surface-muted")}>
        <FileText size={18} strokeWidth={1.7} className="mt-0.5 shrink-0 text-ink-muted" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13.5px] font-medium text-ink-h" title={policy.name}>{policy.name}</span>
          <span className="block text-[12px] text-ink-soft">
            {formatBytes(policy.size_bytes)} · {formatRelativeTime(policy.uploaded_at)}
            {run?.code && ` · ${run.code}`}
          </span>
          <span className={clsx("mt-0.5 flex items-center gap-1.5 text-[12px] font-medium", TONE[line.tone])}>
            {isActive(run) && <span className="size-1.5 animate-pulse rounded-full bg-current" aria-hidden />}
            {line.text}
          </span>
          {run?.status === "running" && run.stage === "extract" && run.progress?.total ? (
            <span className="mt-1 block"><ProgressBar value={run.progress.done / run.progress.total} label={`${policy.name} extraction`} /></span>
          ) : null}
        </span>
      </button>
    </li>
  );
}

function Uploader({ onUploaded }: { onUploaded: (name: string) => void }) {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [code, setCode] = useState("");
  const [share, setShare] = useState(0);

  const upload = useMutation({
    mutationFn: (f: File) => c2.upload(f, code, setShare),
    onSuccess: ({ policy, job }) => {
      qc.setQueryData(runKey(policy.name), job);
      void qc.invalidateQueries({ queryKey: ["c2"] });
      onUploaded(policy.name);
      setFile(null);
      setCode("");
    },
  });

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { "application/pdf": [".pdf"] },
    multiple: false,
    disabled: upload.isPending,
    onDropAccepted: ([f]) => { setFile(f); upload.reset(); },
  });

  return (
    <section aria-label="Upload a policy" className="rounded-2xl border border-line bg-surface p-4 shadow-sm">
      <div {...getRootProps()}
           className={clsx("flex cursor-pointer flex-col items-center rounded-xl border-2 border-dashed px-4 py-6 text-center transition-colors",
             isDragActive ? "border-primary bg-[var(--accent-bg)]" : "border-line hover:border-primary/60")}>
        <input {...getInputProps()} aria-label="Policy PDF" />
        <FileUp size={22} className="text-primary" />
        <p className="mt-2 text-[13.5px] font-medium text-ink-h">
          {isDragActive ? "Drop the PDF here" : "Drop a policy PDF or click to choose"}
        </p>
        <p className="mt-0.5 text-[12px] text-ink-soft">Standards, amendments and Acts are added to the graph</p>
      </div>

      {file && (
        <div className="mt-3 flex flex-col gap-2.5">
          <div className="flex items-center gap-2 rounded-xl bg-surface-muted px-3 py-2 text-[13px]">
            <FileText size={16} className="shrink-0 text-ink-muted" />
            <span className="min-w-0 flex-1 truncate text-ink-h" title={file.name}>{file.name}</span>
            <span className="num text-[12px] text-ink-soft">{formatBytes(file.size)}</span>
            {!upload.isPending && (
              <button type="button" aria-label="Remove file" onClick={() => setFile(null)}
                      className="rounded-full p-0.5 text-ink-muted hover:text-ink-h">
                <X size={14} />
              </button>
            )}
          </div>
          <label className="text-[12px] text-ink-muted">
            Standard code <span className="text-ink-soft">(optional, e.g. LKAS 18, when the file name or title page does not show it)</span>
            <input value={code} onChange={(e) => setCode(e.target.value)} disabled={upload.isPending} placeholder="LKAS 18"
                   className="mt-1 block h-8 w-full rounded-full border border-line bg-input px-3 text-[13px] text-ink-h outline-none focus:border-primary" />
          </label>
          {upload.isPending && <ProgressBar value={share < 1 ? share : undefined} label="Upload" />}
          <Button variant="primary" disabled={upload.isPending} onClick={() => upload.mutate(file)}>
            <FileUp size={15} />
            {upload.isPending ? (share < 1 ? `Uploading ${Math.round(share * 100)}%` : "Reading the PDF…") : "Upload and update the graph"}
          </Button>
        </div>
      )}
      {upload.error && <p role="alert" className="mt-2 text-[13px] text-danger">{upload.error.message}</p>}
    </section>
  );
}
