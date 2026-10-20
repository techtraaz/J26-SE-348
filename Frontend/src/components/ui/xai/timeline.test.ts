import { describe, expect, it } from "vitest";

import fixture from "./__fixtures__/sse_events.json";
import {
  buildRuns,
  isFoldedPass,
  runHeadline,
  runTitle,
  stageSummary,
  type XaiEvent,
} from "./timeline";

// Recorded from Component-04: an audit of ACME-1, a Copilot question about it,
// and a Copilot turn in a general chat that audited case NEW-1.
const caseStream = fixture["ACME-1"] as XaiEvent[];
const chatStream = fixture["GEN-20261020-AB12"] as XaiEvent[];

describe("buildRuns", () => {
  it("groups a case stream into its audit run and Copilot turn", () => {
    const runs = buildRuns(caseStream);
    expect(runs.map((r) => r.kind)).toEqual(["audit", "copilot"]);
    const [audit, turn] = runs;
    expect(audit.status).toBe("done");
    // compliance and anomaly run in parallel, so their order may vary
    const ids = audit.stages.map((s) => s.id);
    expect(ids[0]).toBe("data_quality");
    expect(ids.slice(1, 3).sort()).toEqual(["anomaly", "compliance"]);
    expect(ids.slice(3)).toEqual(["reasoning", "evidence_validation"]);
    expect(audit.stages.every((s) => s.status === "done")).toBe(true);
    expect(audit.totalFindings).toBeGreaterThan(0);
    expect(audit.insight).toMatch(/balance sheet does not balance/);
    expect(turn.question).toMatch(/why did CHK-001 fail/);
    expect(turn.stages.map((s) => s.label)).toEqual(["Understanding the request", "Preparing the answer"]);
  });

  it("keeps failed checks visible and folds passing checks", () => {
    const compliance = buildRuns(caseStream)[0].stages.find((s) => s.id === "compliance")!;
    const failed = compliance.steps.filter((s) => s.tone === "danger");
    expect(failed.map((s) => s.target)).toContain("CHK-001 on BS");
    expect(failed.find((s) => s.target === "CHK-001 on BS")!.facts.length).toBeGreaterThan(3);
    expect(stageSummary(compliance)).toMatch(/evaluated \d+ checks, \d+ failed/);
    const dq = buildRuns(caseStream)[0].stages.find((s) => s.id === "data_quality")!;
    expect(dq.steps.filter(isFoldedPass).length).toBe(3);
  });

  it("shows an audit started from a chat on that chat's stream", () => {
    const runs = buildRuns(chatStream);
    expect(runs.map((r) => [r.kind, r.caseId])).toEqual([
      ["copilot", "GEN-20261020-AB12"], ["audit", "NEW-1"],
    ]);
    expect(runTitle(runs[1])).toBe("Audit of NEW-1 · v1");
  });

  it("is live: a run in progress is running until its end event", () => {
    const end = caseStream.findIndex((e) => e.event_type === "agent_done" && e.stage === "reasoning");
    const partial = buildRuns(caseStream.slice(0, end));
    expect(partial[0].status).toBe("running");
    expect(partial[0].stages.at(-1)!.status).toBe("running");
  });

  it("writes a Claude-style headline", () => {
    expect(runHeadline(buildRuns(caseStream)[0])).toMatch(
      /^Read 3 documents, ran \d+ checks, and \d+ more steps$/,
    );
  });

  it("is order-stable and pure", () => {
    expect(buildRuns(caseStream)).toEqual(buildRuns(caseStream));
  });
});
