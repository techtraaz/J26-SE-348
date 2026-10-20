import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { c3, chat } from "@/lib/apiClient";
import { caseTitle, dateGroup } from "@/lib/caseList";
import { useUI } from "@/store/ui";
import type { AuditDocument, CaseSummary, ChatSession } from "@/types/audit";
import { CasesSidebar } from "./CasesSidebar";

vi.mock("@/lib/apiClient", () => ({
  c3: { cases: vi.fn() },
  chat: { clear: vi.fn(), sessions: vi.fn(), rename: vi.fn() },
}));

const DOC: AuditDocument = {
  doc_id: "INV-1", doc_type: "invoice", period_year: 2026, parent_doc_id: null, name: "04_Tax_Invoice_COI-1158.pdf",
  fields: {}, confidences: {}, methods: {},
};

function summary(over: Partial<CaseSummary>): CaseSummary {
  return { case_id: "CASE-A", title: "Tax Invoice COI-1158", verdict: "issues_found", score: 75, version: 1,
           status: "pending_auditor_review", created_at: new Date().toISOString(), docs: 1, findings: 1, high: 1,
           needs_review: 0, materiality: null, ...over };
}

function session(over: Partial<ChatSession>): ChatSession {
  const now = new Date().toISOString();
  return { session_id: "CASE-A", case_id: "CASE-A", title: "CASE-A", created_at: now, updated_at: now, ...over };
}

function renderSidebar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><CasesSidebar /></QueryClientProvider>);
}

afterEach(() => vi.unstubAllGlobals());

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}")));
  vi.mocked(c3.cases).mockResolvedValue([]);
  vi.mocked(chat.sessions).mockResolvedValue([]);
  vi.mocked(chat.clear).mockResolvedValue(undefined as never);
  vi.mocked(chat.rename).mockResolvedValue(undefined as never);
  useUI.setState({ sidebarOpen: true, selectedCase: null, staged: { "CASE-1": [DOC] }, generalSessionId: "GEN-1" });
});

describe("CasesSidebar", () => {
  it("names a case after its documents and shows its verdict", async () => {
    vi.mocked(c3.cases).mockResolvedValue([summary({})]);
    renderSidebar();
    const row = await screen.findByRole("button", { name: /Tax Invoice COI-1158 Issues found · 75 · v1/ });
    expect(row.getAttribute("title")).toContain("CASE-A"); // the id stays available on hover
    expect(screen.getByRole("button", { name: /Tax Invoice COI-1158 1 document\(s\) ready · not audited/ }))
      .toBeTruthy(); // the draft with a staged document
  });

  it("shows the auditor's name for a renamed case", async () => {
    vi.mocked(c3.cases).mockResolvedValue([summary({})]);
    vi.mocked(chat.sessions).mockResolvedValue([session({ title: "Q3 supplier invoices" })]);
    renderSidebar();
    expect(await screen.findByText("Q3 supplier invoices")).toBeTruthy();
  });

  it("renames a case from its options menu", async () => {
    vi.mocked(c3.cases).mockResolvedValue([summary({})]);
    useUI.setState({ staged: {} });
    renderSidebar();
    await userEvent.click(await screen.findByRole("button", { name: "Options for Tax Invoice COI-1158" }));
    await userEvent.click(screen.getByRole("menuitem", { name: /Rename/ }));
    const box = screen.getByRole("textbox", { name: "Case name" });
    await userEvent.clear(box);
    await userEvent.type(box, "Q3 supplier invoices{Enter}");
    expect(chat.rename).toHaveBeenCalledWith("CASE-A", "Q3 supplier invoices", "CASE-A");
  });

  it("never lists a new case that holds nothing, and reuses it", async () => {
    useUI.setState({ staged: {} });
    renderSidebar();
    await userEvent.click(screen.getByRole("button", { name: "New case" }));
    const first = useUI.getState().selectedCase;
    expect(first).toMatch(/^CASE-/);
    expect(screen.getByRole("button", { name: "New case" }).getAttribute("aria-current")).toBe("page");
    expect(screen.queryByText("Untitled case")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "New case" }));
    expect(useUI.getState().selectedCase).toBe(first);
  });

  it("lists a draft once it has chat messages", async () => {
    useUI.setState({ staged: {} });
    vi.mocked(chat.sessions).mockResolvedValue([session({ session_id: "CASE-D", case_id: "CASE-D", title: "CASE-D" }),
                                                session({ session_id: "GEN-1", case_id: null, title: "General questions" })]);
    renderSidebar();
    expect(await screen.findByRole("button", { name: /Untitled case not audited yet/ })).toBeTruthy();
  });

  it("groups cases by date and filters them once the list is long", async () => {
    const day = 86400000;
    vi.mocked(c3.cases).mockResolvedValue(Array.from({ length: 8 }, (_, i) => summary({
      case_id: `C-${i}`, title: `Case ${i}`, created_at: new Date(Date.now() - i * 2 * day).toISOString() })));
    useUI.setState({ staged: {} });
    renderSidebar();
    const today = await screen.findByRole("region", { name: "Today" });
    expect(within(today).getByText("Case 0")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Older" })).toBeTruthy();
    await userEvent.type(screen.getByRole("searchbox", { name: "Search cases" }), "case 3");
    expect(screen.queryByText("Case 0")).toBeNull();
    expect(screen.getByText("Case 3")).toBeTruthy();
  });

  it("clears a chat from its options menu only after a second click", async () => {
    renderSidebar();
    await userEvent.click(await screen.findByRole("button", { name: "Options for Tax Invoice COI-1158" }));
    const item = screen.getByRole("menuitem", { name: /Clear chat/ });
    await userEvent.click(item);
    expect(chat.clear).not.toHaveBeenCalled();
    expect(item.textContent).toContain("Click again to clear");
    await userEvent.click(item);
    expect(chat.clear).toHaveBeenCalledWith("CASE-1");
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(expect.stringMatching(/\/xai\/history\/CASE-1$/),
                                                  { method: "DELETE" });
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

describe("case names and date groups", () => {
  it("names a case after the document the others support", () => {
    const po = { ...DOC, doc_id: "PO", doc_type: "purchase_order", name: "03a_Purchase_Order_PO-1.pdf", parent_doc_id: "INV-1" };
    expect(caseTitle([po, DOC])).toBe("Tax Invoice COI-1158 + 1 more");
    expect(caseTitle([{ ...po, parent_doc_id: null }, DOC])).toBe("Tax Invoice COI-1158 + 1 more"); // unlinked PO
    expect(caseTitle([{ ...DOC, name: undefined, doc_type: "balance_sheet" }])).toBe("Balance sheet");
    expect(caseTitle([])).toBe("Untitled case");
  });

  it("puts a date in the right group", () => {
    const now = new Date(2026, 9, 21, 9);
    expect(dateGroup(new Date(2026, 9, 21, 1).toISOString(), now)).toBe("Today");
    expect(dateGroup(new Date(2026, 9, 20, 23).toISOString(), now)).toBe("Yesterday");
    expect(dateGroup(new Date(2026, 9, 15).toISOString(), now)).toBe("Previous 7 days");
    expect(dateGroup(new Date(2026, 8, 1).toISOString(), now)).toBe("Older");
    expect(dateGroup(null, now)).toBe("Today");
  });
});
