import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useUI } from "@/store/ui";
import fixture from "./__fixtures__/sse_events.json";
import { ThinkingTimeline } from "./ThinkingTimeline";
import { buildRuns, type XaiEvent } from "./timeline";

// A chat reply's "Explain" button opens the panel on exactly that reply's trace.

const caseStream = fixture["ACME-1"] as XaiEvent[];
const [auditRun] = buildRuns(caseStream); // not the latest run, so collapsed by default

afterEach(() => vi.useRealTimers());

describe("Explain a chat reply", () => {
  it("opens the panel on the Thinking tab with that run in focus", () => {
    useUI.setState({ xaiPanelOpen: false, xaiActiveTab: "report", xaiFocus: null });
    useUI.getState().explainRun("trace-123");
    const s = useUI.getState();
    expect([s.xaiPanelOpen, s.xaiActiveTab, s.xaiFocus?.runKey]).toEqual([true, "thinking", "trace-123"]);
  });

  it("expands and highlights the focused run", () => {
    render(<ThinkingTimeline events={caseStream} connected streamId="ACME-1"
                             focus={{ runKey: auditRun.key, at: 1 }} />);
    const run = screen.getByRole("region", { name: /Audit of ACME-1/ });
    expect(run.classList.contains("xai-focused")).toBe(true);
    expect(run.querySelector("[aria-expanded]")!.getAttribute("aria-expanded")).toBe("true");
  });

  it("says so when the reply's trace is no longer kept", () => {
    vi.useFakeTimers();
    render(<ThinkingTimeline events={caseStream} connected streamId="ACME-1"
                             focus={{ runKey: "gone", at: 2 }} />);
    expect(screen.queryByRole("status")).toBeNull();
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.getByRole("status").textContent).toContain("no longer available");
  });
});
