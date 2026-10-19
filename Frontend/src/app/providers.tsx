import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";
import { queryKeys } from "@/features/extraction/api/hooks";
import { router } from "./router";

const qc = new QueryClient();
// Component-01 pages poll while documents are processed; these defaults apply to
// their queries only, so the rest of the app keeps React Query's defaults.
qc.setQueryDefaults(queryKeys.all, { retry: 1, staleTime: 3000, refetchOnWindowFocus: false });

export function Providers() {
  return (
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
