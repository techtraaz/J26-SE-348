import { useState } from "react";
import { api, call } from "@/features/extraction/api/client";
import type { VerifiedRecord } from "@/features/extraction/api/types";
import type { ReviewResult } from "@/features/documents/ReviewPanel";
import { c3 } from "@/lib/apiClient";
import { useUI } from "@/store/ui";
import type { DocumentPreview } from "@/types/review";
import { automaticReview, reviewReasons } from "./verifiedIntake";

export interface IntakeItem {
  documentId: string;
  name: string;
  state: "reading" | "added" | "review" | "error";
  message?: string; // added: what C3 noted; review: why; error: what failed
  record?: VerifiedRecord;
  preview?: DocumentPreview;
  busy?: boolean;
}

/** Picked verified documents on their way into a case: C1's verified record →
 * C3's automatic field matching → the case's staged documents. */
export function useVerifiedIntake(caseId: string) {
  const stageDocs = useUI((s) => s.stageDocs);
  const [items, setItems] = useState<IntakeItem[]>([]);

  const update = (documentId: string, patch: Partial<IntakeItem>) =>
    setItems((all) => all.map((i) => (i.documentId === documentId ? { ...i, ...patch } : i)));

  /** C3 turns the reviewed (or automatic) decisions into case documents. */
  async function addToCase(documentId: string, name: string, record: VerifiedRecord, r: ReviewResult) {
    const out = await c3.confirmC1(caseId, [{
      verified: record, name, doc_type: r.docType, period_year: r.periodYear,
      parent_doc_id: r.parentDocId, fields: r.fields,
    }]);
    stageDocs(caseId, out.case.docs);
    update(documentId, { state: "added", busy: false, message: out.issues.length ? out.issues.join(" ") : undefined });
  }

  async function read(documentId: string, name: string, record: VerifiedRecord, docType?: string) {
    const [preview] = await c3.previewC1(caseId, [{ verified: record, ...(docType ? { doc_type: docType } : {}) }]);
    const automatic = automaticReview(preview);
    if (automatic) await addToCase(documentId, name, record, automatic);
    else update(documentId, { state: "review", busy: false, preview, message: reviewReasons(preview).join(" · ") });
  }

  const fail = (documentId: string, e: unknown) =>
    update(documentId, { state: "error", busy: false, message: e instanceof Error ? e.message : "Something went wrong." });

  /** Start with the picked documents; each runs on its own. */
  function add(documents: { id: string; filename: string }[]) {
    setItems(documents.map((d) => ({ documentId: d.id, name: d.filename, state: "reading" })));
    for (const d of documents) {
      void (async () => {
        try {
          const record = await call(api.GET("/api/v1/documents/{document_id}/verified", {
            params: { path: { document_id: d.id } },
          }));
          update(d.id, { record });
          await read(d.id, d.filename, record);
        } catch (e) {
          fail(d.id, e);
        }
      })();
    }
  }

  /** The reviewer settled what C3 could not. */
  async function confirmReview(item: IntakeItem, r: ReviewResult) {
    if (!item.record) return;
    update(item.documentId, { busy: true });
    try {
      await addToCase(item.documentId, item.name, item.record, r);
    } catch (e) {
      fail(item.documentId, e);
    }
  }

  /** Read again as another document type (the rules differ per type). */
  async function reread(item: IntakeItem, docType: string) {
    if (!item.record) return;
    update(item.documentId, { busy: true });
    try {
      await read(item.documentId, item.name, item.record, docType);
    } catch (e) {
      fail(item.documentId, e);
    }
  }

  const discard = (documentId: string) => setItems((all) => all.filter((i) => i.documentId !== documentId));

  return { items, add, confirmReview, reread, discard };
}
