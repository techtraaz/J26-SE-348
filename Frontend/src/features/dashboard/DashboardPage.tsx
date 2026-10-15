import { useState } from "react";
import { Card } from "@/components/ui/basics";
import { sampleCase, sampleFindings } from "@/mocks/sampleCase";

export function DashboardPage() {
  const [q] = useState("");
  void q;
  const high = sampleFindings.filter((f) => (f as any).severity === "high").length;
  return (
    <div className="flex flex-col gap-4">
      <Card><h3 className="font-bold">Cases · findings by severity · waiting review</h3>
        <p className="text-sm text-[var(--text-muted)]">Case {sampleCase.case_id}: {sampleCase.docs.length} docs, {sampleFindings.length} findings, {high} high.</p>
      </Card>
      <Card><h3 className="font-bold">Trust through traceability</h3>
        <p className="text-sm">Every finding shows evidence, rule ID, policy ID and confidence. Human stays in control.</p>
      </Card>
    </div>
  );
}
