import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Finding, ReplyBlock } from "@/types/audit";
import { Markdown } from "./Markdown";
import { ReplyBlocks } from "./ReplyBlocks";

const FINDING = {
  finding_id: "INV-04-POL-07", rule_id: "POL-07", category: "compliance", severity: "high",
  message: "Only 1 of 2 approvals is signed.", evidence_ids: ["INV-04"], policy_ids: ["POL-07"],
  confidence: 1, review_status: "pending_review", claims: [], reasoning_chain: [],
  evidence_validation: "passed", citation_unverified: false, supersedes: null, created_at: "",
} as unknown as Finding;

function show(blocks: ReplyBlock[], onPick = vi.fn()) {
  render(<ReplyBlocks blocks={blocks} findings={[FINDING]} onPick={onPick} disabled={false} />);
  return onPick;
}

describe("ReplyBlocks", () => {
  it("draws a rule list as one item per rule with its status", () => {
    show([{ type: "list", title: "4 rule(s) apply to an invoice", more: 0, items: [
      { label: "CHK-003 Child amount matches parent", text: "checks `child.amount == parent.amount`", tone: "high", details: [] },
      { label: "POL-07", text: "Purchases above Rs. 100,000 need dual approval", tone: "neutral", details: ["limit Rs 100,000"] },
    ] }]);
    expect(screen.getByRole("heading", { name: "4 rule(s) apply to an invoice" })).toBeInTheDocument();
    const items = screen.getAllByRole("listitem").filter((li) => li.querySelector(".reply-item-label"));
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByText("high")).toHaveClass("tone-chip");
    expect(within(items[0]).getByText("child.amount == parent.amount").tagName).toBe("CODE");
    expect(within(items[1]).getByText("limit Rs 100,000")).toBeInTheDocument();
  });

  it("shows the verdict with its score", () => {
    show([{ type: "verdict", case_id: "C-1", version: 2, verdict: "issues_found", score: 75, summary: "1 rule finding (1 high)." }]);
    expect(screen.getByText("Issues found")).toHaveClass("tone-failed");
    expect(screen.getByText("75")).toBeInTheDocument();
    expect(screen.getByText("Case C-1 · version 2")).toBeInTheDocument();
  });

  it("sends a chosen answer back as the next message", async () => {
    const onPick = show([{ type: "question", text: "Which one should I explain?",
                           choices: ["Why was CHK-001 raised on 02_SFP.pdf?", "Why was POL-07 raised on 04_Invoice.pdf?"] }]);
    await userEvent.click(screen.getByRole("button", { name: "Why was POL-07 raised on 04_Invoice.pdf?" }));
    expect(onPick).toHaveBeenCalledWith("Why was POL-07 raised on 04_Invoice.pdf?");
  });

  it("draws findings as cards, and plain lines for findings it does not have", () => {
    show([{ type: "findings", title: "High severity", finding_ids: ["INV-04-POL-07", "GONE"],
            lines: ["POL-07 · high: Only 1 of 2 approvals is signed.", "CHK-001 · high: off by 5"], more: 1 }]);
    expect(screen.getByText("Only 1 of 2 approvals is signed.")).toBeInTheDocument();
    expect(screen.getByText("CHK-001 · high: off by 5")).toBeInTheDocument();
    expect(screen.getByText("…and 1 more")).toBeInTheDocument();
  });

  it("draws tables and links", () => {
    show([{ type: "table", title: "", columns: ["Version", "Verdict"], rows: [["v1", "issues found"]] },
          { type: "link", label: "Open the PDF report", url: "http://localhost:8004/report/download/x.pdf" }]);
    expect(screen.getByRole("columnheader", { name: "Verdict" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "issues found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the PDF report" })).toHaveAttribute("target", "_blank");
  });
});

describe("Markdown", () => {
  it("renders lists and bold, and never raw HTML", () => {
    render(<Markdown text={"**Rules**\n- CHK-001\n- POL-07\n\n<script>alert(1)</script><b>x</b>"} />);
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(["CHK-001", "POL-07"]);
    expect(screen.getByText("Rules").tagName).toBe("STRONG");
    expect(document.querySelector("script")).toBeNull();
    expect(document.querySelector("b")).toBeNull();
  });
});
