export const routes = {
  dashboard: "/",
  cases: "/cases",
  caseDetail: (id: string) => `/cases/${id}`,
  documents: "/documents",
  findings: "/findings",
  policies: "/policies",
  reports: "/reports",
  settings: "/settings",
} as const;
