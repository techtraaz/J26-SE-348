import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { c3 } from "@/lib/apiClient";
import { useUI } from "@/store/ui";
import type { AuditDocument, AuditResult } from "@/types/audit";
import { CasePanel } from "./CasePanel";

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
    expect(screen.getByText(/Verified documents from the library will be added here/)).toBeInTheDocument();
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

  it("sends the case materiality when one is entered", async () => {
    useUI.setState({ staged: { "CASE-1": [DOC] } });
    vi.mocked(c3.run).mockResolvedValue(RESULT);
    renderPanel();

    await userEvent.type(screen.getByLabelText("Materiality"), "Rs. 50,000");
    await userEvent.click(screen.getByRole("button", { name: "Audit 1 document(s)" }));

    expect(c3.run).toHaveBeenCalledWith({ case_id: "CASE-1", docs: [DOC], materiality: 50000 }, "CASE-1");
  });

  it("refuses a materiality that is not an amount", async () => {
    useUI.setState({ staged: { "CASE-1": [DOC] } });
    vi.mocked(c3.run).mockReset();
    renderPanel();

    await userEvent.type(screen.getByLabelText("Materiality"), "a lot");
    await userEvent.click(screen.getByRole("button", { name: "Audit 1 document(s)" }));

    expect(c3.run).not.toHaveBeenCalled();
    expect(screen.getByText(/Materiality must be an amount/)).toBeInTheDocument();
  });

  it("removes a document from the case", async () => {
    useUI.setState({ staged: { "CASE-1": [DOC] } });
    renderPanel();

    await userEvent.click(screen.getByRole("button", { name: "Remove INV-001" }));

    expect(screen.queryByText("INV-001")).not.toBeInTheDocument();
  });
});
