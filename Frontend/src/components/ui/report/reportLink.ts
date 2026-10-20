// Finding Component-04's report link in a Copilot reply, so the chat can show a
// file card instead of a bare URL. C3's reply reads e.g.
//   "The audit report for case CASE-1 (version 1) is ready: http://localhost:8004/report/download/RPT-….pdf"

const LINK = /(https?:\/\/[^\s]+?\/report\/download\/(RPT-[A-Z0-9-]+\.pdf))/;

export interface ReportLink {
  url: string; // absolute, as C3 sent it
  filename: string; // RPT-….pdf
  text: string; // the reply without the URL
}

export function findReportLink(text: string): ReportLink | null {
  const m = LINK.exec(text);
  if (!m) return null;
  const rest = text.replace(m[1], "").replace(/:\s*$/, ".").replace(/\s+\./, ".").trim();
  return { url: m[1], filename: m[2], text: rest };
}

/** The same report as an attachment (saved, not shown). */
export function downloadUrl(url: string): string {
  return `${url}${url.includes("?") ? "&" : "?"}download=1`;
}
