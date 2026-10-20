import type { Tone } from "@/types/audit";

/** How each audit verdict is shown (chat verdict card, sidebar). */
export const VERDICT: Record<string, { label: string; tone: Tone }> = {
  clean: { label: "Clean", tone: "passed" },
  issues_found: { label: "Issues found", tone: "failed" },
  needs_review: { label: "Needs review", tone: "review" },
  not_auditable: { label: "Not auditable", tone: "skipped" },
};
