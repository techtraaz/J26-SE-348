import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useUI } from "@/store/ui";
import { VerifiedDocumentPicker } from "./VerifiedDocumentPicker";

const NOW = "2026-10-20T09:00:00Z";
const doc = (id: string, filename: string, status: string, folder_id: string | null = null) => ({
  id, folder_id, filename, mime: "image/png", sha256: "x".repeat(64), status, page_count: 1, source: "demo",
  error_code: null, error_message: null, created_at: NOW, updated_at: NOW, latest_run: null,
});
const record = (id: string) => ({
  document_id: id, version: 1, based_on_run_id: "run-1", confirmed_by: null, confirmed_at: NOW,
  lines: [{ line_id: `${id}-l1`, page: 1, sequence: 0, text: "TOTAL 1,200", confidence: 0.99,
            box: [0, 0, 10, 10], provenance: "paddleocr", escalated: null, human_action: "accepted" }],
});
const preview = (id: string, year: number | null) => ({
  document_id: id, human_verified: true,
  source: { component: "C1", document_id: id, run_id: "run-1", verified_version: 1, confirmed_by: null },
  suggestions: { doc_type: { value: "invoice", evidence: "INVOICE", line_id: `${id}-l1` },
                 period_year: year ? { value: year, evidence: String(year), line_id: `${id}-l1` } : null },
  doc_type: "invoice",
  fields: [{ field: "amount", value: 1200, method: "rules", label: "TOTAL", needs_confirmation: false, confidence: 1,
             line: { line_id: `${id}-l1`, page: 1, text: "TOTAL 1,200", confidence: 0.99, box: [0, 0, 10, 10] },
             label_line: null, alternatives: [] }],
  unmapped_lines: [], missing_fields: [], rules_not_runnable: [], field_names: ["amount"],
  llm: { used: false, error: null }, line_count: 1,
});

/** C1 (library, verified records) and C3 (preview, confirm), faked. */
function mockApis() {
  const confirms: Record<string, unknown>[] = [];
  const documentQueries: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: Request | string, init?: RequestInit) => {
    const request = typeof input === "string" ? new Request(input, init) : input;
    const url = new URL(request.url);
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

    if (url.pathname === "/api/v1/folders") {
      return json({ items: url.searchParams.get("parent_id") ? [] : [
        { id: "f1", parent_id: null, name: "Invoices 2025", created_at: NOW, folder_count: 0, document_count: 1 }] });
    }
    if (url.pathname === "/api/v1/folders/f1") {
      return json({ id: "f1", parent_id: null, name: "Invoices 2025", created_at: NOW, folder_count: 0,
                    document_count: 1, breadcrumbs: [{ id: "f1", name: "Invoices 2025" }] });
    }
    if (url.pathname === "/api/v1/documents") {
      documentQueries.push(url.search);
      const items = url.searchParams.get("folder_id") === "f1"
        ? [doc("c", "march.png", "verified", "f1")]
        : [doc("a", "complete.png", "verified"), doc("b", "no-year.png", "verified"), doc("x", "draft.png", "needs_review")];
      return json({ items, total: items.length, limit: 200, offset: 0 });
    }
    const verified = url.pathname.match(/^\/api\/v1\/documents\/(\w+)\/verified$/);
    if (verified) return json(record(verified[1]));
    if (url.pathname === "/audit/intake/c1/preview") {
      const body = await request.json();
      const id = body.documents[0].verified.document_id;
      return json({ case_id: body.case_id, documents: [preview(id, id === "b" ? null : 2025)] });
    }
    if (url.pathname === "/audit/intake/c1/confirm") {
      const body = await request.json();
      const d = body.documents[0];
      confirms.push(d);
      return json({ case: { case_id: body.case_id, docs: [{ doc_id: d.verified.document_id, doc_type: d.doc_type,
                    period_year: d.period_year, fields: { amount: 1200 } }] }, issues: [] });
    }
    return json({ error: { code: "not_found", message: `Not found: ${url.pathname}` } }, 404);
  }));
  return { confirms, documentQueries };
}

function renderPicker() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onClose = vi.fn();
  render(<QueryClientProvider client={client}><VerifiedDocumentPicker caseId="CASE-1" onClose={onClose} /></QueryClientProvider>);
  return { onClose };
}

beforeEach(() => useUI.setState({ staged: {} }));
afterEach(() => vi.unstubAllGlobals());

describe("VerifiedDocumentPicker", () => {
  it("offers only verified documents, and says how many are not verified yet", async () => {
    mockApis();
    renderPicker();

    expect(await screen.findByText("complete.png")).toBeInTheDocument();
    expect(screen.getByText("no-year.png")).toBeInTheDocument();
    expect(screen.queryByText("draft.png")).not.toBeInTheDocument();
    expect(screen.getByText(/1 document here is not verified yet/)).toBeInTheDocument();
  });

  it("browses into a folder", async () => {
    const { documentQueries } = mockApis();
    renderPicker();

    await userEvent.click(await screen.findByRole("button", { name: /Invoices 2025/ }));

    expect(await screen.findByText("march.png")).toBeInTheDocument();
    expect(documentQueries.at(-1)).toContain("folder_id=f1");
  });

  it("adds a complete document without asking, and asks only about the one without a year", async () => {
    const { confirms } = mockApis();
    renderPicker();

    await userEvent.click(await screen.findByRole("checkbox", { name: /complete.png/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /no-year.png/ }));
    expect(screen.getByText("2 documents selected")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add to case" }));

    // complete.png: matched by C3 and added with no clicks.
    expect(await screen.findByText("Added to CASE-1.")).toBeInTheDocument();
    expect(confirms[0]).toMatchObject({ doc_type: "invoice", period_year: 2025, parent_doc_id: null,
                                        fields: [{ field: "amount", line_id: "a-l1" }] });
    expect((confirms[0].verified as { document_id: string }).document_id).toBe("a");
    expect(useUI.getState().staged["CASE-1"].map((d) => d.doc_id)).toEqual(["a"]);

    // no-year.png: Senuthi's review panel, for the year only.
    expect(await screen.findByText(/Needs you: no year found/)).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText("YYYY"), "2024");
    await userEvent.click(screen.getByRole("button", { name: "Add to case" }));

    await waitFor(() => expect(confirms).toHaveLength(2));
    expect(confirms[1]).toMatchObject({ doc_type: "invoice", period_year: 2024 });
    expect(useUI.getState().staged["CASE-1"].map((d) => d.doc_id)).toEqual(["a", "b"]);
    expect(within(screen.getByRole("status")).getByText("2 added")).toBeInTheDocument();
  });

  it("shows when C3 cannot be reached", async () => {
    mockApis();
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const url = new URL(input instanceof Request ? input.url : String(input));
      if (url.pathname.startsWith("/audit")) throw new TypeError("Failed to fetch");
      if (url.pathname === "/api/v1/documents") {
        return new Response(JSON.stringify({ items: [doc("a", "complete.png", "verified")], total: 1, limit: 200, offset: 0 }),
                            { headers: { "content-type": "application/json" } });
      }
      if (url.pathname === "/api/v1/folders") return new Response(JSON.stringify({ items: [] }), { headers: { "content-type": "application/json" } });
      return new Response(JSON.stringify(record("a")), { headers: { "content-type": "application/json" } });
    });
    renderPicker();

    await userEvent.click(await screen.findByRole("checkbox", { name: /complete.png/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add to case" }));

    expect(await screen.findByText(/Cannot reach http:\/\/localhost:8003/)).toBeInTheDocument();
    expect(useUI.getState().staged["CASE-1"]).toBeUndefined();
  });
});
