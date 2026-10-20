import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import fixture from "./__fixtures__/sse_events.json";
import { ThinkingTimeline } from "./ThinkingTimeline";
import type { XaiEvent } from "./timeline";

const caseStream = fixture["ACME-1"] as XaiEvent[];

function renderStream(events: XaiEvent[]) {
  return render(<ThinkingTimeline events={events} connected streamId="ACME-1" />);
}

describe("ThinkingTimeline", () => {
  it("shows one dropdown per run with its headline", () => {
    renderStream(caseStream);
    const audit = screen.getByRole("region", { name: /Audit of ACME-1/ });
    expect(within(audit).getByRole("button", { name: /Read 3 documents, ran \d+ checks/ })).toBeTruthy();
    expect(screen.getByRole("region", { name: /why did CHK-001 fail/ })).toBeTruthy();
  });

  it("opens stages with failures and highlights the failed check in red", async () => {
    renderStream(caseStream);
    const audit = screen.getByRole("region", { name: /Audit of ACME-1/ });
    await userEvent.click(within(audit).getByRole("button", { name: /Read 3 documents/ }));
    const failed = within(audit).getByRole("button", { name: /Failed CHK-001 on BS/ });
    expect(failed.closest(".xai-step-failed")).not.toBeNull();
    expect(failed.textContent).toContain("Assets 100 ≠ Liabilities + Capital 50");

    await userEvent.click(failed);
    const facts = failed.parentElement!.querySelector("dl")!;
    expect(facts.textContent).toContain("Difference");
    expect(facts.textContent).toContain("assets == liabilities + capital");
  });

  it("folds passing checks into one row that can be opened", async () => {
    renderStream(caseStream);
    const audit = screen.getByRole("region", { name: /Audit of ACME-1/ });
    await userEvent.click(within(audit).getByRole("button", { name: /Read 3 documents/ }));
    await userEvent.click(within(audit).getByRole("button", { name: /^Data quality/ }));
    const group = within(audit).getByRole("button", { name: "3 checks passed" });
    await userEvent.click(group);
    expect(within(audit).getAllByRole("button", { name: /^Checked / }).length).toBeGreaterThanOrEqual(3);
  });

  it("shows a spinner on the running stage while an audit is in progress", () => {
    const end = caseStream.findIndex((e) => e.event_type === "agent_done" && e.stage === "reasoning");
    const { container } = renderStream(caseStream.slice(0, end));
    expect(container.querySelectorAll(".xai-spin").length).toBeGreaterThan(0);
    // the headline names the current stage ("Reasoning · …"), the stage row is open
    const stageRow = screen.getAllByRole("button", { name: /^Reasoning/ })
      .find((b) => b.classList.contains("xai-row"))!;
    expect(stageRow.getAttribute("aria-expanded")).toBe("true");
  });

  it("never uses placeholder wording", async () => {
    const { container } = renderStream(caseStream);
    for (const button of screen.getAllByRole("button")) {
      if (button.getAttribute("aria-expanded") === "false") await userEvent.click(button);
    }
    expect(container.textContent).not.toMatch(/\b(sample|fake|mock|test)\b/i);
  });
});
