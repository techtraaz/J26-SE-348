import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import type { AuditDocument } from "@/types/audit";

// Chat history is saved by Component-03 (/chat). The browser keeps only UI state.
type UIState = {
  theme: "light" | "dark";
  selectedCase: string | null; // a case's chat (session_id = case_id); null = general chat
  generalSessionId: string; // this browser's general-questions chat
  draftCases: string[]; // started here, not audited yet
  staged: Record<string, AuditDocument[]>; // documents waiting to be sent, per case
  xaiPanelOpen: boolean;
  sidebarOpen: boolean; // the Cases sidebar in Chat
  xaiActiveTab: "thinking" | "report";
  // The run a chat reply's "Explain" asked the panel to show (not persisted).
  xaiFocus: { runKey: string; at: number } | null;
  toggleTheme: () => void;
  setCase: (id: string | null) => void;
  newCase: () => string;
  stageDocs: (caseId: string, docs: AuditDocument[]) => void;
  unstage: (caseId: string, docId: string) => void;
  // Which staged document this one supports (e.g. a PO or GRN supports an invoice); null = none.
  setParent: (caseId: string, docId: string, parentId: string | null) => void;
  clearStaged: (caseId: string) => void;
  toggleXaiPanel: () => void;
  toggleSidebar: () => void;
  setXaiTab: (tab: "thinking" | "report") => void;
  explainRun: (runKey: string) => void;
};

const stamp = () => {
  const d = new Date();
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
};
const random = () => Math.random().toString(36).slice(2, 6).toUpperCase();

export const useUI = create<UIState>()(
  persist(
    (set) => ({
      theme: "light",
      selectedCase: null,
      generalSessionId: `GEN-${stamp()}-${random()}`,
      draftCases: [],
      staged: {},
      xaiPanelOpen: false,
      sidebarOpen: true,
      xaiActiveTab: "thinking",
      xaiFocus: null,
      toggleTheme: () => set((s) => ({ theme: s.theme === "light" ? "dark" : "light" })),
      setCase: (id) => set({ selectedCase: id }),
      newCase: () => {
        const id = `CASE-${stamp()}-${random()}`;
        set((s) => ({ selectedCase: id, draftCases: [id, ...s.draftCases] }));
        return id;
      },
      stageDocs: (caseId, docs) =>
        set((s) => {
          const kept = (s.staged[caseId] ?? []).filter((d) => !docs.some((n) => n.doc_id === d.doc_id));
          return { staged: { ...s.staged, [caseId]: [...kept, ...docs] } };
        }),
      unstage: (caseId, docId) =>
        set((s) => ({ staged: { ...s.staged, [caseId]: (s.staged[caseId] ?? []).filter((d) => d.doc_id !== docId) } })),
      setParent: (caseId, docId, parentId) =>
        set((s) => ({ staged: { ...s.staged, [caseId]: (s.staged[caseId] ?? []).map((d) =>
          d.doc_id === docId ? { ...d, parent_doc_id: parentId } : d) } })),
      clearStaged: (caseId) => set((s) => ({ staged: { ...s.staged, [caseId]: [] } })),
      toggleXaiPanel: () => set((s) => ({ xaiPanelOpen: !s.xaiPanelOpen })),
      toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
      setXaiTab: (tab) => set({ xaiActiveTab: tab }),
      explainRun: (runKey) =>
        set({ xaiPanelOpen: true, xaiActiveTab: "thinking", xaiFocus: { runKey, at: Date.now() } }),
    }),
    {
      name: "nomos-ui",
      version: 2, // v1 kept chat messages here; they now live on the server
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({ theme: s.theme, selectedCase: s.selectedCase, generalSessionId: s.generalSessionId,
                            draftCases: s.draftCases, staged: s.staged, sidebarOpen: s.sidebarOpen }),
      migrate: (old) => {
        const { messages: _dropped, ...rest } = (old ?? {}) as Record<string, unknown>;
        void _dropped;
        return rest as unknown as UIState;
      },
    },
  ),
);
