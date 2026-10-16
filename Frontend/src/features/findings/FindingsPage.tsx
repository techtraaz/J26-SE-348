import { Card } from "@/components/ui/basics";
import { sampleFindings } from "@/mocks/sampleCase";
import { SeverityBadge } from "@/components/audit/badges";

export function FindingsPage() {
  return (
    <Card>
      <h3 className="font-bold">Findings — click evidence to open source</h3>
      {(sampleFindings as any[]).map((f) => (
        <div key={f.finding_id} className="mt-2 border-t pt-2 text-sm">
          <SeverityBadge s={f.severity} /> <span className="id">{f.rule_id}</span> · {f.message}
        </div>
      ))}
    </Card>
  );
}
