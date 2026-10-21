import type { Severity } from "@/types/audit";
import { AlertTriangle, CheckCircle, Info, XCircle } from "lucide-react";

const map: Record<Severity, { bg: string; icon: React.ReactNode }> = {
  high: { bg: "background:color-mix(in srgb,var(--danger) 14%,var(--surface));color:var(--danger)", icon: <XCircle size={14} /> },
  medium: { bg: "background:color-mix(in srgb,var(--warning) 16%,var(--surface));color:var(--warning)", icon: <AlertTriangle size={14} /> },
  low: { bg: "background:color-mix(in srgb,var(--info) 14%,var(--surface));color:var(--info)", icon: <Info size={14} /> },
};

export function SeverityBadge({ s }: { s: Severity }) {
  const m = map[s];
  return <span className="id inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-bold" style={{ background: m.bg.split(";")[0].split(":")[1], color: m.bg.split(";")[1].split(":")[1] }}>{m.icon}{s}</span>;
}

export function ConfidenceBadge({ v }: { v: number }) {
  const label = v >= 0.8 ? "High" : v >= 0.5 ? "Medium" : "Low · needs review";
  return <span className="rounded-full border border-[var(--border)] px-2 py-0.5 text-xs">{label} ({v.toFixed(2)})</span>;
}

export function EvidenceChip({ id, onOpen }: { id: string; onOpen?: () => void }) {
  return <button onClick={onOpen} className="id rounded-md bg-[var(--surface-muted)] px-2 py-0.5 text-xs underline">{id}</button>;
}

export function EmptyState({ text }: { text: string }) {
  return <div className="rounded-xl border border-dashed border-[var(--border)] p-6 text-center text-sm text-[var(--text-muted)]"><CheckCircle size={16} className="mx-auto mb-1" />{text}</div>;
}

export function ErrorState({ text }: { text: string }) {
  return <div className="rounded-xl border border-[var(--danger)] bg-[color-mix(in_srgb,var(--danger)_10%,var(--surface))] p-4 text-sm">{text}</div>;
}
