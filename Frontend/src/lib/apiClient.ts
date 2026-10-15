import { env } from "@/config/env";

async function post(base: string, path: string, body: unknown) {
  if (!base) throw new Error("Backend not configured (mock mode).");
  const r = await fetch(`${base}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`Request failed: ${r.status}`);
  return r.json();
}

export const api = {
  // C3 live. C1/C2/C4 use mock until their backends are ready.
  c3AuditRun: (payload: unknown) => post(env.c3Base, "/audit/run", payload),
  c3Copilot: (payload: unknown) => post(env.c3Base, "/copilot/query", payload),
};
