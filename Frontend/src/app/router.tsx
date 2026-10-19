import { createBrowserRouter } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { LibraryLayout } from "@/features/documents/LibraryLayout";
import { PoliciesPage } from "@/features/policies/PoliciesPage";
import { ReportsPage } from "@/features/reports/ReportsPage";
import { SettingsPage } from "@/features/dashboard/SettingsPage";
import { LibraryPage } from "@/features/extraction/library/LibraryPage";
import { DocumentPage } from "@/features/extraction/review/DocumentPage";
import { routes } from "@/config/routes";

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: routes.dashboard, element: <DashboardPage /> },
      {
        path: routes.documents,
        element: <LibraryLayout />,
        children: [
          { index: true, element: <LibraryPage /> },
          { path: "folders/:folderId", element: <LibraryPage /> },
          { path: ":documentId", element: <DocumentPage /> },
        ],
      },
      { path: routes.policies, element: <PoliciesPage /> },
      { path: routes.reports, element: <ReportsPage /> },
      { path: routes.settings, element: <SettingsPage /> },
    ],
  },
]);
