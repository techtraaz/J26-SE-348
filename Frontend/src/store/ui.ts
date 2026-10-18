import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import type { AuditDocument, Finding } from "@/types/audit";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  findings?: Finding[];
  suggestions?: string[];
  attached?: number; // documents sent with this message
  error?: boolean;
}

type UIState = {
  theme: "light" | "dark";
  selectedCase: string | null; // one chat session = one case
  draftCases: string[]; // started in this browser, not audited yet
  messages: Record<string, ChatMessage[]>;
  staged: Record<string, AuditDocument[]>; // documents waiting to be sent, per case
  toggleTheme: () => void;
  setCase: (id: string | null) => void;
  newCase: () => string;
  addMessage: (caseId: string, m: ChatMessage) => void;
  stageDocs: (caseId: string, docs: AuditDocument[]) => void;
  unstage: (caseId: string, docId: string) => void;
  clearStaged: (caseId: string) => void;
};

function newCaseId(): string {
  const d = new Date();
  const day = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
  return `CASE-${day}-${Math.random().toString(36).slice(2, 6).toUpperCase()}`;
}

// Chat history and staged documents live in this browser only.
export const useUI = create<UIState>()(
  persist(
    (set) => ({
      theme: "light",
      selectedCase: null,
      draftCases: [],
      messages: {},
      staged: {},
      toggleTheme: () => set((s) => ({ theme: s.theme === "light" ? "dark" : "light" })),
      setCase: (id) => set({ selectedCase: id }),
      newCase: () => {
        const id = newCaseId();
        set((s) => ({ selectedCase: id, draftCases: [id, ...s.draftCases] }));
        return id;
      },
      addMessage: (caseId, m) =>
        set((s) => ({ messages: { ...s.messages, [caseId]: [...(s.messages[caseId] ?? []), m] } })),
      stageDocs: (caseId, docs) =>
        set((s) => {
          const kept = (s.staged[caseId] ?? []).filter((d) => !docs.some((n) => n.doc_id === d.doc_id));
          return { staged: { ...s.staged, [caseId]: [...kept, ...docs] } };
        }),
      unstage: (caseId, docId) =>
        set((s) => ({ staged: { ...s.staged, [caseId]: (s.staged[caseId] ?? []).filter((d) => d.doc_id !== docId) } })),
      clearStaged: (caseId) => set((s) => ({ staged: { ...s.staged, [caseId]: [] } })),
    }),
    {
      name: "nomos-ui",
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({ theme: s.theme, selectedCase: s.selectedCase, draftCases: s.draftCases,
                            messages: s.messages, staged: s.staged }),
    },
  ),
);
