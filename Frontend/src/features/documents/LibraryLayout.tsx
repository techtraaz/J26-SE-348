import { ExtractionLayout } from "@/features/extraction/ExtractionLayout";
import { CasePanel } from "./CasePanel";

// The Library tab: Component-01's document library (search + routed page) with
// the case panel on the right. Narrow screens stack the panel below.
export function LibraryLayout() {
  return (
    <div className="flex min-w-0 flex-1 flex-col lg:flex-row">
      <ExtractionLayout />
      <aside className="shrink-0 border-t border-[var(--border-light)] lg:w-80 lg:border-l lg:border-t-0">
        <CasePanel />
      </aside>
    </div>
  );
}
