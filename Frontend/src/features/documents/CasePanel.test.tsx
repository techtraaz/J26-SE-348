import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { c3 } from "@/lib/apiClient";
import { useUI } from "@/store/ui";
import type { AuditDocument, AuditResult } from "@/types/audit";
import { CasePanel } from "./CasePanel";

/** Component 01's library with nothing in it (the picker reads it). */
function emptyLibrary() {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(input instanceof Request ? input.url : String(input));
    const body = url.pathname === "/api/v1/documents" ? { items: [], total: 0, limit: 200, offset: 0 } : { items: [] };
    return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });
  }));
}

afterEach(() => vi.unstubAllGlobals());

vi.mock("@/lib/apiClient", () => ({
  c3: { cases: vi.fn(), run: vi.fn(), appendEvidence: vi.fn() },
}));

const DOC: AuditDocument = {
  doc_id: "INV-001", doc_type: "invoice", period_year: 2025, parent_doc_id: null,
  fields: { total: 1200 }, confidences: {}, methods: {},
};

const RESULT: AuditResult = {
  case_id: "CASE-1", version: 1, kg_source: "mock", latency_ms: 10, status: "pending_auditor_review",
  findings: [], trace: [], rejected_records: [], rejected_citations: [], events_published: false,
  created_at: "2026-10-19T00:00:00Z",
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><CasePanel /></MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(c3.cases).mockResolvedValue([]);
  vi.mocked(c3.run).mockReset();
  useUI.setState({ selectedCase: "CASE-1", draftCases: ["CASE-1"], staged: {} });
});

describe("CasePanel", () => {
  it("offers no way to upload documents into a case", () => {
    const { container } = renderPanel();

    expect(container.querySelector('input[type="file"]')).toBeNull();
    expect(screen.queryByRole("button", { name: /choose files/i })).not.toBeInTheDocument();
    expect(screen.getByText("No documents in this case yet.")).toBeInTheDocument();
  });

  it("picks verified documents for the selected case, as the chat does", async () => {
    emptyLibrary();
    renderPanel();

    await userEvent.click(screen.getByRole("button", { name: /add verified/i }));

    expect(screen.getByRole("dialog", { name: "Add verified documents to CASE-1" })).toBeInTheDocument();
    expect(await screen.findByText("No verified documents here.")).toBeInTheDocument();
  });

  it("starts a new case when none is chosen", async () => {
    emptyLibrary();
    useUI.setState({ selectedCase: null });
    renderPanel();
    expect(screen.getByText(/Choose a case, or add verified documents to start a new one/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /add verified/i }));

    const created = useUI.getState().selectedCase;
    expect(created).toMatch(/^CASE-/);
    expect(screen.getByRole("dialog", { name: `Add verified documents to ${created}` })).toBeInTheDocument();
  });

  it("audits the case's documents and shows the summary", async () => {
    useUI.setState({ staged: { "CASE-1": [DOC] } });
    vi.mocked(c3.run).mockResolvedValue(RESULT);
    renderPanel();

    expect(screen.getByText("INV-001")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Audit 1 document(s)" }));

    expect(c3.run).toHaveBeenCalledWith({ case_id: "CASE-1", docs: [DOC] }, "CASE-1");
    await waitFor(() => expect(screen.getByText(/Case CASE-1 version 1 saved/)).toBeInTheDocument());
    expect(useUI.getState().staged["CASE-1"]).toEqual([]);
  });

  it("removes a document from the case", async () => {
    useUI.setState({ staged: { "CASE-1": [DOC] } });
    renderPanel();

    await userEvent.click(screen.getByRole("button", { name: "Remove INV-001" }));

    expect(screen.queryByText("INV-001")).not.toBeInTheDocument();
  });
});
