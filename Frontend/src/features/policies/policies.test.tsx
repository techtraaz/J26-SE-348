import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { KgChanges, Policy, PolicyRun } from "@/types/policies";
import { layoutChanges } from "./graphLayout";
import { runLine, stepStates } from "./stages";

const policy: Policy = {
  name: "LKAS_02_Inventories.pdf", size_bytes: 2048, uploaded_at: "2026-10-21T08:00:00Z",
  last_run: {
    job_id: "j1", status: "done", stage: null, progress: null, kind: "standard", code: "LKAS 2",
    error: null, finished_at: "2026-10-21T08:01:00Z", added: { nodes: 8, relationships: 15 },
    requirements: 1, definitions: 0, equations: 0, llm_unavailable: null,
  },
};

const changes: KgChanges = {
  new: { Requirement: [{ key: "LKAS 2:41#R1", caption: "Disclose inventories pledged as security", section: "LKAS 2:41" }] },
  graph: {
    truncated: false,
    nodes: [
      { id: "Standard:LKAS 2", label: "Standard", key: "LKAS 2", caption: "LKAS 2 Inventories", new: false },
      { id: "Section:LKAS 2:9", label: "Section", key: "LKAS 2:9", caption: "Measurement", new: false },
      { id: "Section:LKAS 2:41", label: "Section", key: "LKAS 2:41", caption: "Disclosure", new: true },
      { id: "Requirement:LKAS 2:41#R1", label: "Requirement", key: "LKAS 2:41#R1", caption: "Disclose", new: true },
    ],
    links: [
      { source: "Standard:LKAS 2", target: "Section:LKAS 2:9", type: "HAS_SECTION" },
      { source: "Standard:LKAS 2", target: "Section:LKAS 2:41", type: "HAS_SECTION" },
      { source: "Section:LKAS 2:41", target: "Requirement:LKAS 2:41#R1", type: "HAS_REQUIREMENT" },
    ],
  },
};

const run: PolicyRun = {
  job_id: "j1", file: policy.name, code: "LKAS 2", status: "done", kind: "standard", stage: null,
  stages_done: ["chunk", "classify", "retrieve_context", "extract", "validate", "resolve", "write"],
  queued_at: "2026-10-21T08:00:00Z", started_at: "2026-10-21T08:00:01Z", finished_at: "2026-10-21T08:01:00Z",
  totals: { before: { nodes: 100, relationships: 200 }, after: { nodes: 108, relationships: 215 } },
  summary: {
    chunks: 2, sent_to_llm: 2, skipped: 0, llm_errors: 0, llm_unavailable: null, requirements: 1,
    definitions: 0, equations: 0, created: { Requirement: 1, Section: 1, SourceChunk: 2 },
    matched: { Section: 1 }, proposals: 0, plan_errors: [], written: 8,
  },
  changes,
};

vi.mock("@/lib/apiClient", async (orig) => ({
  ...(await orig<typeof import("@/lib/apiClient")>()),
  c2: {
    policies: vi.fn(async () => [policy]),
    run: vi.fn(async () => run),
    reingest: vi.fn(),
    upload: vi.fn(),
    fileUrl: (name: string) => `http://c2/policies/${name}/file`,
  },
}));

describe("stepStates", () => {
  it("marks finished, running and waiting steps", () => {
    const s = stepStates({ ...run, status: "running", stage: "extract", stages_done: ["chunk", "classify", "retrieve_context"] });
    expect([s.stored, s.classify, s.extract, s.write]).toEqual(["done", "done", "running", "pending"]);
  });

  it("warns on extraction when the LLM was offline", () => {
    const s = stepStates({ ...run, summary: { ...run.summary!, llm_unavailable: "down" } });
    expect(s.extract).toBe("warning");
    expect(s.write).toBe("done");
  });

  it("skips the rest when the document is not a standard", () => {
    const s = stepStates({ ...run, kind: "unknown", stages_done: ["chunk", "classify"] });
    expect([s.classify, s.extract]).toEqual(["done", "skipped"]);
  });
});

describe("runLine", () => {
  it("shows extraction progress while running", () => {
    expect(runLine({ ...policy.last_run!, status: "running", stage: "extract", progress: { done: 3, total: 9 } }).text)
      .toBe("LLM extraction 3/9");
  });

  it("shows what was added", () => {
    expect(runLine(policy.last_run)).toEqual({ tone: "success", text: "+8 nodes" });
  });
});

describe("layoutChanges", () => {
  it("puts the standard in the middle and paragraphs with new facts first", () => {
    const l = layoutChanges(changes.graph, "file.pdf", 1);
    expect(l.center?.node.key).toBe("LKAS 2");
    expect(l.nodes.filter((p) => p.ring === 1).map((p) => p.node.key)).toEqual(["LKAS 2:41"]);
    expect(l.nodes.find((p) => p.ring === 2)?.node.key).toBe("LKAS 2:41#R1");
    expect(l.hiddenSections).toBe(1);
  });
});

describe("PoliciesPage", () => {
  it("lists stored policies and shows the graph changes of the selected one", async () => {
    const { PoliciesPage } = await import("./PoliciesPage");
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter><PoliciesPage /></MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("+8 nodes")).toBeInTheDocument();
    expect(await screen.findByText("What changed in the knowledge graph")).toBeInTheDocument();
    expect(screen.getByText("108")).toBeInTheDocument();
    expect(screen.getByText("Disclose inventories pledged as security")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open pdf/i })).toHaveAttribute("href", "http://c2/policies/LKAS_02_Inventories.pdf/file");
  });
});
