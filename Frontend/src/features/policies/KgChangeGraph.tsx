import { useMemo, useState } from "react";
import type { KgChanges } from "@/types/policies";
import { KG_COLORS, layoutChanges, SIZE, sectionNumber, type Placed } from "./graphLayout";

const RADIUS = { 0: 20, 1: 8, 2: 6 } as const;

/** The part of the graph one run touched. New nodes are bright with a gold ring;
 * nodes that were already there are faded. */
export function KgChangeGraph({ graph, title }: { graph: KgChanges["graph"]; title: string }) {
  const layout = useMemo(() => layoutChanges(graph, title), [graph, title]);
  const [focus, setFocus] = useState<Placed | null>(null);
  const shown = focus ?? layout.center;
  const labelSections = layout.nodes.filter((p) => p.ring === 1).length <= 36;

  if (layout.nodes.length <= 1) {
    return <p className="py-10 text-center text-[13px] text-ink-muted">No paragraphs to draw for this run.</p>;
  }
  return (
    <div>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" className="mx-auto block w-full max-w-[560px]"
           aria-label={`Knowledge graph changes: ${graph.nodes.filter((n) => n.new).length} new nodes`}>
        {layout.edges.map((e, i) => (
          <line key={i} x1={e.from.x} y1={e.from.y} x2={e.to.x} y2={e.to.y}
                stroke={e.fresh ? "var(--kg-new)" : "var(--border-strong)"}
                strokeOpacity={e.fresh ? 0.75 : 0.6} strokeWidth={e.fresh ? 1.4 : 1} />
        ))}
        {layout.nodes.map((p, i) => {
          const r = RADIUS[p.ring];
          const active = focus?.node.id === p.node.id;
          return (
            <g key={`${i}-${p.node.id}`} style={{ cursor: "pointer" }}
               onMouseEnter={() => setFocus(p)} onClick={() => setFocus(p)}>
              <title>{`${p.node.label} ${p.node.key}${p.node.new ? " (new)" : ""}\n${p.node.caption}`}</title>
              {p.node.new && p.ring > 0 && (
                <circle className="kg-new-ring" cx={p.x} cy={p.y} r={r} fill="none" stroke="var(--kg-new)" strokeWidth={2} />
              )}
              <circle cx={p.x} cy={p.y} r={active ? r + 2.5 : r} fill={KG_COLORS[p.node.label] ?? "var(--kg-other)"}
                      fillOpacity={p.node.new || p.ring === 0 ? 1 : 0.4}
                      stroke={p.node.new ? "var(--kg-new)" : "var(--surface)"} strokeWidth={p.node.new ? 2 : 1.5} />
              {p.ring === 1 && labelSections && (
                <text x={p.x + (SIZE / 2 - p.x) * 0.13} y={p.y + (SIZE / 2 - p.y) * 0.13 + 3.5} textAnchor="middle"
                      fontSize={11} fill="var(--text-muted)" style={{ pointerEvents: "none" }}>
                  {sectionNumber(p.node.key)}
                </text>
              )}
            </g>
          );
        })}
        <text x={SIZE / 2} y={SIZE / 2 + 38} textAnchor="middle" fontSize={13} fontWeight={600}
              fill="var(--text-h)" style={{ pointerEvents: "none" }}>
          {layout.center?.node.key}
        </text>
      </svg>

      {/* what the pointer is on */}
      <div className="mt-2 min-h-[64px] rounded-xl border border-line-light bg-surface-muted/60 px-3.5 py-2.5 text-[13px]">
        {shown && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-block size-2.5 rounded-full"
                    style={{ background: KG_COLORS[shown.node.label] ?? "var(--kg-other)" }} aria-hidden />
              <span className="font-semibold text-ink-h">{shown.node.label}</span>
              <code className="text-[12px] text-ink-muted">{shown.node.key}</code>
              {shown.node.new && (
                <span className="rounded-full bg-[color-mix(in_srgb,var(--kg-new)_22%,transparent)] px-2 py-0.5 text-[11px] font-semibold text-ink-h">
                  new
                </span>
              )}
            </div>
            {shown.node.caption !== shown.node.key && <p className="mt-1 text-ink">{shown.node.caption}</p>}
          </>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12px] text-ink-muted">
        {["Standard", "Section", "Requirement", "Definition", "Equation"].map((label) => (
          <span key={label} className="inline-flex items-center gap-1.5">
            <span className="inline-block size-2.5 rounded-full" style={{ background: KG_COLORS[label] }} aria-hidden />
            {label}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-full border-2" style={{ borderColor: "var(--kg-new)" }} aria-hidden />
          new in this run
        </span>
        <span>faded = already in the graph</span>
      </div>
      {(layout.hiddenSections > 0 || layout.hiddenChildren > 0 || graph.truncated) && (
        <p className="mt-1.5 text-[12px] text-ink-soft">
          Showing the paragraphs with the most new facts
          {layout.hiddenSections > 0 && ` · ${layout.hiddenSections} more paragraphs not drawn`}
          {layout.hiddenChildren > 0 && ` · ${layout.hiddenChildren} more facts not drawn`}. Every new node is listed below.
        </p>
      )}
    </div>
  );
}
