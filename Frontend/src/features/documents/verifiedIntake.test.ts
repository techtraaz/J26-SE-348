import { describe, expect, it } from "vitest";

import type { DocumentPreview, PreviewField } from "@/types/review";
import { automaticReview, reviewReasons } from "./verifiedIntake";

function field(name: string, lineId: string, extra: Partial<PreviewField> = {}): PreviewField {
  return {
    field: name, value: 1200, method: "rules", label: name, needs_confirmation: false, confidence: 1,
    line: { line_id: lineId, page: 1, text: `${name} 1,200`, confidence: 0.99, box: [0, 0, 10, 10] },
    label_line: null, alternatives: [], ...extra,
  };
}

function preview(extra: Partial<DocumentPreview> = {}): DocumentPreview {
  return {
    document_id: "doc-1", human_verified: true,
    source: { component: "C1", document_id: "doc-1", run_id: "run-1", verified_version: 2, confirmed_by: null },
    suggestions: {
      doc_type: { value: "invoice", evidence: "TAX INVOICE", line_id: "l1" },
      period_year: { value: 2025, evidence: "03 Mar 2025", line_id: "l2" },
    },
    doc_type: "invoice",
    fields: [field("amount", "l7"), field("tax", "l8")],
    unmapped_lines: [], missing_fields: [], rules_not_runnable: [], field_names: ["amount", "tax"],
    llm: { used: false, error: null }, line_count: 12, ...extra,
  };
}

describe("automaticReview", () => {
  it("adds a complete document as C3 read it", () => {
    expect(automaticReview(preview())).toEqual({
      docType: "invoice", periodYear: 2025, parentDocId: null,
      fields: [{ field: "amount", line_id: "l7" }, { field: "tax", line_id: "l8" }],
    });
  });

  it("accepts a year C3 found as text", () => {
    const p = preview({ suggestions: { doc_type: null, period_year: { value: "2024", evidence: "FY 2024", line_id: "l2" } } });
    expect(automaticReview(p)?.periodYear).toBe(2024);
  });
});

describe("reviewReasons", () => {
  it("is empty when nothing is in doubt", () => {
    expect(reviewReasons(preview())).toEqual([]);
  });

  it.each([
    [{ doc_type: "unknown" }, "no document type found"],
    [{ suggestions: { doc_type: null, period_year: null } }, "no year found"],
    [{ suggestions: { doc_type: null, period_year: { value: "12/10", evidence: "12/10", line_id: "l2" } } }, "no year found"],
    [{ missing_fields: ["amount", "date"] }, "missing amount, date"],
    [{ fields: [field("amount", "l7", { method: "llm" })] }, "1 AI match to confirm"],
    [{ fields: [field("amount", "l7", { needs_confirmation: true }), field("tax", "l8", { method: "llm" })] }, "2 AI matches to confirm"],
  ] as [Partial<DocumentPreview>, string][])("asks a person when %o", (change, reason) => {
    const p = preview(change);
    expect(reviewReasons(p)).toContain(reason);
    expect(automaticReview(p)).toBeNull();
  });
});
