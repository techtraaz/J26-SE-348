import { useState } from "react";
import type { Finding } from "@/types/audit";
import { SeverityBadge } from "@/components/audit/badges";

const VALIDATION_LABEL: Record<Finding["evidence_validation"], string> = {
  passed: "values verified",
  existence_only: "evidence exists",
  failed: "citation failed",
  unverified: "no evidence",
};

/** One finding: summary first, reasoning on demand. */
export function FindingCard({ f }: { f: Finding }) {
  const [open, setOpen] = useState(false);
  const review = f.review_status === "needs_more_evidence";
  const isReviewItem = f.rule_id.startsWith("REV-");
  return (
    <div style={{
      border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: "10px 12px",
      background: "var(--bg)", fontSize: "13px",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
        <SeverityBadge s={f.severity} />
        <span className="id" style={{ fontWeight: 600, color: "var(--text-h)" }}>{f.rule_id}</span>
        {isReviewItem && <Tag text="review item" />}
        {review && !isReviewItem && <Tag text="needs review" />}
        {f.citation_unverified && <Tag text="citation failed" danger />}
        <span style={{ marginLeft: "auto", color: "var(--text-soft)", fontSize: "12px" }}>
          {VALIDATION_LABEL[f.evidence_validation]} · conf {f.confidence.toFixed(2)}
        </span>
      </div>
      <p style={{ margin: "6px 0 0", lineHeight: 1.5 }}>{f.message}</p>
      <div style={{ display: "flex", gap: "6px", marginTop: "6px", flexWrap: "wrap", alignItems: "center" }}>
        {f.evidence_ids.map((e) => (
          <span key={e} className="id" style={{ background: "var(--surface-muted)", borderRadius: "6px", padding: "1px 6px", fontSize: "12px" }}>{e}</span>
        ))}
        {f.reasoning_chain.length > 0 && (
          <button onClick={() => setOpen(!open)} style={{
            marginLeft: "auto", background: "none", border: "none", cursor: "pointer",
            color: "var(--text-muted)", fontSize: "12px", fontFamily: "inherit", padding: 0,
          }}>{open ? "Hide reasoning" : "Why?"}</button>
        )}
      </div>
      {open && (
        <ol style={{ margin: "8px 0 0", paddingLeft: "18px", color: "var(--text-muted)", fontSize: "12px", lineHeight: 1.6 }}>
          {f.reasoning_chain.map((step, i) => <li key={i}>{step}</li>)}
        </ol>
      )}
    </div>
  );
}

function Tag({ text, danger }: { text: string; danger?: boolean }) {
  return (
    <span style={{
      fontSize: "11px", borderRadius: "var(--radius-pill)", padding: "1px 8px",
      border: `1px solid ${danger ? "var(--danger)" : "var(--border)"}`,
      color: danger ? "var(--danger)" : "var(--text-muted)",
    }}>{text}</span>
  );
}
