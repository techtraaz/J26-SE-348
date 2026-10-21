import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReportFileCard } from "./ReportFileCard";
import { downloadUrl, findReportLink } from "./reportLink";

const URL = "http://localhost:8004/report/download/RPT-20261020-172855-4QIB.pdf";
const REPLY = `The audit report for case CASE-SAMPLE-01 (version 1) is ready: ${URL}`;

afterEach(() => vi.unstubAllGlobals());

describe("report link in a Copilot reply", () => {
  it("is found and taken out of the text", () => {
    expect(findReportLink(REPLY)).toEqual({
      url: URL, filename: "RPT-20261020-172855-4QIB.pdf",
      text: "The audit report for case CASE-SAMPLE-01 (version 1) is ready.",
    });
    expect(findReportLink("Case CASE-1 has 2 findings.")).toBeNull();
    expect(downloadUrl(URL)).toBe(`${URL}?download=1`);
  });
});

describe("ReportFileCard", () => {
  function renderCard() {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ reports: [{
      report_id: "RPT-20261020-172855-4QIB", filename: "RPT-20261020-172855-4QIB.pdf", audit_id: "CASE-SAMPLE-01:v1",
      version: 1, verdict: "clean", score: 100, generated_at: "2026-10-20T17:28:55+00:00", size_bytes: 10503,
      download_url: "/report/download/RPT-20261020-172855-4QIB.pdf",
    }] }), { headers: { "content-type": "application/json" } })));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(<QueryClientProvider client={qc}>
      <ReportFileCard url={URL} filename="RPT-20261020-172855-4QIB.pdf" caseId="CASE-SAMPLE-01" />
    </QueryClientProvider>);
  }

  it("shows the report as a file with its verdict, size and a download button", async () => {
    renderCard();
    const card = await screen.findByRole("group", { name: "Audit report · CASE-SAMPLE-01 v1" });
    expect(card.textContent).toContain("Document · PDF");
    expect(card.textContent).toContain("Clean");
    expect(card.textContent).toContain("10 KB");
    expect(within(card).getByRole("link", { name: /Download/ }).getAttribute("href")).toBe(`${URL}?download=1`);
  });

  it("opens the in-app viewer from the card or from the menu", async () => {
    renderCard();
    await userEvent.click(await screen.findByRole("group", { name: /Audit report/ }));
    expect(screen.getByRole("dialog").querySelector("iframe")!.getAttribute("src")).toContain(URL);
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "More options" }));
    await userEvent.click(screen.getByRole("menuitem", { name: /View/ }));
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open full size" }).getAttribute("href")).toBe(URL);
  });
});
