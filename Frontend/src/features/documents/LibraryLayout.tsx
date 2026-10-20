import { useMatch } from "react-router-dom";
import { routes } from "@/config/routes";
import { ExtractionLayout } from "@/features/extraction/ExtractionLayout";
import { CasePanel } from "./CasePanel";

// The Library tab: Component-01's document library (title, search, routed page)
// with the case panel as a full-height right column. Its content stays in view
// while the library scrolls. Narrow screens stack the panel below. The panel is
// hidden on a document's review page, which needs the width.
export function LibraryLayout() {
  // "/documents/folders" has the same shape as a document's page: it is not one.
  const match = useMatch(`${routes.documents}/:documentId`);
  const reviewing = match !== null && match.params.documentId !== "folders";
  return (
    <div className="flex min-w-0 flex-1 flex-col lg:flex-row">
      <ExtractionLayout />
      {!reviewing && (
        <aside className="shrink-0 border-t border-line-light bg-surface/40 lg:w-80 lg:border-l lg:border-t-0">
          <div className="lg:sticky lg:top-0 lg:max-h-screen lg:overflow-y-auto">
            <CasePanel />
          </div>
        </aside>
      )}
    </div>
  );
}
