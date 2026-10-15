export const AGENTS = [
  "Data Quality",
  "Compliance",
  "Anomaly",
  "Reasoning",
  "Evidence Validation",
] as const;

export const FINDING_STATUS = [
  "pending_review",
  "confirmed",
  "dismissed",
  "needs_more_evidence",
] as const;

// Confidence cut-offs — agree with Jayanath (C1). Low = needs review.
export const CONF_HIGH = 0.8;
export const CONF_MEDIUM = 0.5;
