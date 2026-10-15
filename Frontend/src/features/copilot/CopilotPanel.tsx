import { useState } from "react";
import { Card, Button } from "@/components/ui/basics";
import { api } from "@/lib/apiClient";

const QUICK = [
  { label: "Ask about a rule", text: "what is the rule limit?" },
  { label: "Add evidence to this case", text: "add new bill to case" },
  { label: "Run a new audit", text: "check this year books" },
];

export function CopilotPanel({ caseId }: { caseId: string }) {
  const [text, setText] = useState(QUICK[0].text);
  const [out, setOut] = useState<any>(null);
  const [err, setErr] = useState("");
  async function ask(t: string) {
    setText(t); setErr("");
    try {
      setOut(await api.c3Copilot({ text: t, case_id: caseId }));
    } catch (e: any) {
      setErr(e.message);
    }
  }
  return (
    <Card>
      <h3 className="font-bold">Audit Copilot</h3>
      <div className="mt-2 flex flex-col gap-1">
        {QUICK.map((q) => <Button key={q.label} onClick={() => ask(q.text)}>{q.label}</Button>)}
      </div>
      <input className="mt-2 w-full rounded-lg border p-2 text-sm" value={text} onChange={(e) => setText(e.target.value)} />
      <Button className="mt-2" onClick={() => ask(text)}>Ask</Button>
      {out && <p className="mt-2 text-sm">Intent: <b>{out.intent}</b> — {out.reply}</p>}
      {err && <p className="mt-2 text-sm text-[var(--danger)]">{err}</p>}
    </Card>
  );
}
