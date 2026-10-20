import { useMemo } from "react";
import { useQuery, type QueryClient } from "@tanstack/react-query";
import { c3, chat } from "@/lib/apiClient";
import { useUI } from "@/store/ui";
import type { AuditDocument, CaseSummary } from "@/types/audit";

// The cases the auditor sees (sidebar, Library): audited cases, plus drafts that
// already hold something (staged documents or chat messages). A new case with
// nothing in it is never listed, like a new chat in a chat app.

export type CaseEntry = {
  case_id: string;
  title: string;
  custom: boolean; // renamed by the auditor
  summary: CaseSummary | null; // null = not audited yet
  staged: number; // documents waiting for the audit
  at: string | null; // last activity; null = only staged documents
};

/** Same rule as C3's store.doc_title: "04_Tax_Invoice_X.pdf" -> "Tax Invoice X". */
export function docTitle(d: Pick<AuditDocument, "name" | "doc_type">): string {
  const stem = (d.name ?? "").replace(/\.[A-Za-z0-9]{2,5}$/, "").replace(/^\d+[A-Za-z]?[_\- ]+/, "")
    .replace(/_/g, " ").trim();
  if (stem) return stem;
  const type = (d.doc_type || "document").replace(/_/g, " ");
  return type.charAt(0).toUpperCase() + type.slice(1);
}

const SUPPORTING_TYPES = new Set(["purchase_order", "goods_received_note", "receipt", "payment_voucher"]);

/** Same rule as C3's store.case_title: the main document (the one others support, else the
 *  first that is not a PO, GRN...) plus a count. */
export function caseTitle(docs: AuditDocument[]): string {
  if (!docs.length) return "Untitled case";
  const parents = new Set(docs.map((d) => d.parent_doc_id));
  const main = docs.find((d) => parents.has(d.doc_id))
    ?? docs.find((d) => !SUPPORTING_TYPES.has(d.doc_type)) ?? docs[0];
  return docTitle(main) + (docs.length > 1 ? ` + ${docs.length - 1} more` : "");
}

/** Today / Yesterday / Previous 7 days / Older, by the case's last activity. */
export function dateGroup(iso: string | null, now = new Date()): string {
  if (!iso) return "Today";
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((day(now) - day(new Date(iso))) / 86400000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days <= 7) return "Previous 7 days";
  return "Older";
}

const latest = (a: string | null, b: string | null) => (!a ? b : !b ? a : a > b ? a : b);

export function useCaseList() {
  const { staged, selectedCase, newCase } = useUI();
  const cases = useQuery({ queryKey: ["c3-cases"], queryFn: c3.cases, retry: false });
  const sessions = useQuery({ queryKey: ["chat-sessions"], queryFn: chat.sessions, retry: false });

  const entries = useMemo((): CaseEntry[] => {
    const chats = new Map((sessions.data ?? []).filter((s) => s.case_id).map((s) => [s.session_id, s]));
    const named = (id: string) => {
      const t = chats.get(id)?.title;
      return t && t !== id ? t : null;
    };
    const audited = (cases.data ?? []).map((c): CaseEntry => ({
      case_id: c.case_id, title: named(c.case_id) ?? c.title ?? c.case_id, custom: !!named(c.case_id),
      summary: c, staged: staged[c.case_id]?.length ?? 0,
      at: latest(c.created_at, chats.get(c.case_id)?.updated_at ?? null),
    }));
    const known = new Set(audited.map((e) => e.case_id));
    const draftIds = new Set([
      ...Object.keys(staged).filter((id) => staged[id]?.length),
      ...chats.keys(),
    ].filter((id) => !known.has(id)));
    const drafts = [...draftIds].map((id): CaseEntry => ({
      case_id: id, title: named(id) ?? caseTitle(staged[id] ?? []), custom: !!named(id),
      summary: null, staged: staged[id]?.length ?? 0, at: chats.get(id)?.updated_at ?? null,
    }));
    // Drafts with only staged documents are being worked on now: they go first.
    const key = (e: CaseEntry) => e.at ?? "￿";
    return [...drafts, ...audited].sort((a, b) => (key(a) < key(b) ? 1 : key(a) > key(b) ? -1 : 0));
  }, [cases.data, sessions.data, staged]);

  const listed = new Set(entries.map((e) => e.case_id));
  return {
    entries,
    error: (cases.error as Error | null) ?? null,
    // The selected case is a new one with nothing in it yet.
    blank: selectedCase !== null && !listed.has(selectedCase),
    // Reuse the blank case already open instead of starting another one.
    startNewCase: () => (selectedCase !== null && !listed.has(selectedCase) ? selectedCase : newCase()),
    titleOf: (id: string | null) => entries.find((e) => e.case_id === id)?.title ?? "New case",
  };
}

/** After anything that changes a case or its chat. */
export function refreshCaseList(qc: QueryClient) {
  return Promise.all([qc.invalidateQueries({ queryKey: ["c3-cases"] }),
                      qc.invalidateQueries({ queryKey: ["chat-sessions"] })]);
}
