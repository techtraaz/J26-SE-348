import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { c3, chat } from "@/lib/apiClient";
import { useUI } from "@/store/ui";
import { CasesSidebar } from "./CasesSidebar";

vi.mock("@/lib/apiClient", () => ({
  c3: { cases: vi.fn() },
  chat: { clear: vi.fn() },
}));

function renderSidebar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><CasesSidebar /></QueryClientProvider>);
}

beforeEach(() => {
  vi.mocked(c3.cases).mockResolvedValue([]);
  vi.mocked(chat.clear).mockResolvedValue(undefined as never);
  useUI.setState({ sidebarOpen: true, selectedCase: null, draftCases: ["CASE-1"], generalSessionId: "GEN-1" });
});

describe("CasesSidebar", () => {
  it("clears a chat from its options menu only after a second click", async () => {
    renderSidebar();
    await userEvent.click(await screen.findByRole("button", { name: "Options for CASE-1" }));
    const item = screen.getByRole("menuitem", { name: /Clear chat/ });
    await userEvent.click(item);
    expect(chat.clear).not.toHaveBeenCalled();
    expect(item.textContent).toContain("Click again to clear");
    await userEvent.click(item);
    expect(chat.clear).toHaveBeenCalledWith("CASE-1");
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("collapses to a rail and back", async () => {
    renderSidebar();
    await userEvent.click(screen.getByRole("button", { name: "Hide sidebar" }));
    expect(useUI.getState().sidebarOpen).toBe(false);
    expect(screen.queryByText("General questions")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Show sidebar" }));
    expect(screen.getByText("General questions")).toBeTruthy();
  });
});
