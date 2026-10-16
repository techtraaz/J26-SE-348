import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, Button } from "@/components/ui/basics";
import { SeverityBadge, EvidenceChip, AgentProgress, EmptyState, ErrorState } from "@/components/audit/badges";
import { api } from "@/lib/apiClient";
import { sampleCase } from "@/mocks/sampleCase";
import { AGENTS } from "@/config/constants";
import type { AuditResult } from "@/types/audit";
import { CopilotPanel } from "@/features/copilot/CopilotPanel";

export function CaseWorkspace() {
  const [result, setResult] = useState<AuditResult | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const mockQuery = useQuery({
    queryKey: ["c3-mock"],
    queryFn: async () => sampleCase,
  });

  async function runLive() {
    setBusy(true); setErr("");
    try {
      const j = await api.c3AuditRun(sampleCase);
      setResult(j as AuditResult);
    } catch (e: any) {
      setErr(e.message + " — showing mock below. Start backend on :8003.");
    }
    setBusy(false);
  }

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[220px_1fr_300px]">
      <Card>
        <h3 className="font-bold">Document tree</h3>
        {(mockQuery.data?.docs ?? []).map((d) => (
          <div key={d.doc_id} className="id mt-1 rounded bg-[var(--surface-muted)] p-1 text-xs">
            {d.parent_doc_id ? `└ ${d.doc_id} (${d.doc_type})` : `${d.doc_id} (${d.doc_type})`}
            {d.confidences && Object.entries(d.confidences).map(([k, v]) => v < 0.5 && <span key={k}> · {k} needs review</span>)}
          </div>
        ))}
      </Card>
      <div className="flex flex-col gap-4">
        <Card>
          <AgentProgress steps={[...AGENTS]} done={result ? 5 : 0} />
          <div className="mt-2"><Button onClick={runLive} disabled={busy}>{busy ? "Running…" : "Run audit (C3 live, mock fallback)"}</Button></div>
          {err && <div className="mt-2"><ErrorState text={err} /></div>}
        </Card>
        <Card>
          <h3 className="font-bold">Findings — summary first</h3>
          {!result && <EmptyState text="No live run yet. Mock has 2 findings. Click Run audit." />}
          {result?.findings.map((f) => (
            <div key={f.finding_id} className="mt-2 border-t border-[var(--border)] pt-2 text-sm">
              <SeverityBadge s={f.severity} /> <span className="id">{f.rule_id}</span> · {f.message}
              <div className="mt-1 flex gap-1">{f.evidence_ids.map((e) => <EvidenceChip key={e} id={e} />)}</div>
            </div>
          ))}
        </Card>
      </div>
      <CopilotPanel caseId={sampleCase.case_id} />
    </div>
  );
}
