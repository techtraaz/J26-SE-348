import type { ReviewResult } from "@/features/documents/ReviewPanel";
import type { DocumentPreview } from "@/types/review";

// Picking verified C1 documents into a case (M5.4, decided 2026-10-20): C3
// matches the lines to fields automatically; a person reviews only what C3
// could not settle on its own.

/** Why a document needs a person before it joins the case (empty = it does not). */
export function reviewReasons(p: DocumentPreview): string[] {
  const reasons: string[] = [];
  if (!p.doc_type || p.doc_type === "unknown") reasons.push("no document type found");
  if (periodYear(p) === null) reasons.push("no year found");
  if (p.missing_fields.length) reasons.push(`missing ${p.missing_fields.join(", ")}`);
  const ai = p.fields.filter((f) => f.method === "llm" || f.needs_confirmation).length;
  if (ai) reasons.push(`${ai} AI match${ai === 1 ? "" : "es"} to confirm`);
  return reasons;
}

/** The decisions C3 needs to add the document unchanged, when nothing is in doubt. */
export function automaticReview(p: DocumentPreview): ReviewResult | null {
  const year = periodYear(p);
  if (reviewReasons(p).length || year === null) return null;
  return {
    docType: p.doc_type,
    periodYear: year,
    parentDocId: null,
    // Rule matches as C3 read them: a value always comes from its cited line.
    fields: p.fields.map((f) => ({ field: f.field, line_id: f.line.line_id })),
  };
}

/** The suggested year, if it is a plausible four-digit year (C3 never guesses it). */
function periodYear(p: DocumentPreview): number | null {
  const year = Number(p.suggestions.period_year?.value);
  return Number.isInteger(year) && year >= 1900 && year <= 2999 ? year : null;
}
