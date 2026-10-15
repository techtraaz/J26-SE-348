import { createBrowserRouter } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { CaseWorkspace } from "@/features/cases/CaseWorkspace";
import { DocumentsPage } from "@/features/documents/DocumentsPage";
import { FindingsPage } from "@/features/findings/FindingsPage";
import { PoliciesPage } from "@/features/policies/PoliciesPage";
import { ReportsPage } from "@/features/reports/ReportsPage";
import { SettingsPage } from "@/features/dashboard/SettingsPage";
import { routes } from "@/config/routes";

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: routes.dashboard, element: <DashboardPage /> },
      { path: routes.cases, element: <CaseWorkspace /> },
      { path: "/cases/:id", element: <CaseWorkspace /> },
      { path: routes.documents, element: <DocumentsPage /> },
      { path: routes.findings, element: <FindingsPage /> },
      { path: routes.policies, element: <PoliciesPage /> },
      { path: routes.reports, element: <ReportsPage /> },
      { path: routes.settings, element: <SettingsPage /> },
    ],
  },
]);
