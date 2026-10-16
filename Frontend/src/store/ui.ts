import { create } from "zustand";

type UIState = {
  theme: "light" | "dark";
  selectedCase: string;
  copilotOpen: boolean;
  toggleTheme: () => void;
  setCase: (id: string) => void;
  setCopilot: (open: boolean) => void;
};

export const useUI = create<UIState>((set) => ({
  theme: "light",
  selectedCase: "CASE-TV",
  copilotOpen: true,
  toggleTheme: () => set((s) => ({ theme: s.theme === "light" ? "dark" : "light" })),
  setCase: (id) => set({ selectedCase: id }),
  setCopilot: (open) => set({ copilotOpen: open }),
}));
