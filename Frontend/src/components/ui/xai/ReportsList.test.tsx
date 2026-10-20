import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReportItem } from "@/components/ui/report/reports";
import { ReportsList } from "./ReportsList";

const REPORT: ReportItem = {
  report_id: "RPT-20261020-152303-DLG0", filename: "RPT-20261020-152303-DLG0.pdf",
  audit_id: "CASE-SAMPLE-02:v1", version: 1, verdict: "issues_found", score: 75,
  generated_at: "2026-10-20T15:23:03+00:00", size_bytes: 11560,
  download_url: "/report/download/RPT-20261020-152303-DLG0.pdf",
};

function renderList(caseId: string | null, reports: ReportItem[]) {
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify({ case_id: caseId, reports }), { headers: { "content-type": "application/json" } })));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><ReportsList caseId={caseId} /></QueryClientProvider>);
}

afterEach(() => vi.unstubAllGlobals());

describe("Report tab", () => {
  it("lists a case's reports with view and download, and no generate button", async () => {
    renderList("CASE-SAMPLE-02", [REPORT]);
    await userEvent.click(await screen.findByRole("button", { name: /View/ }));
    const viewer = screen.getByRole("dialog", { name: "Audit report · CASE-SAMPLE-02 v1" });
    expect(viewer.querySelector("iframe")!.getAttribute("src"))
      .toMatch(/\/report\/download\/RPT-20261020-152303-DLG0\.pdf#toolbar=0/);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("link", { name: /Download/ }).getAttribute("href")).toMatch(/\?download=1$/);
    expect(screen.getByText("Issues found")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /generate/i })).toBeNull();
  });

  it("tells the user to ask the Copilot when there is no report yet", async () => {
    renderList("CASE-SAMPLE-02", []);
    expect((await screen.findByText(/No reports yet/)).textContent).toBeTruthy();
    expect(screen.getByText(/generate the report/)).toBeTruthy();
  });
});
