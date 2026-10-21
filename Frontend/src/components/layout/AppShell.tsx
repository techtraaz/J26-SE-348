import { NavLink, Outlet, useMatch } from "react-router-dom";
import { Sparkles } from "lucide-react";
import { useUI } from "@/store/ui";
import { routes } from "@/config/routes";
import { XaiPanel } from "@/components/ui/XaiPanel";
import { CasesSidebar } from "@/components/layout/CasesSidebar";
import { BrandImage, HeaderArt, SkyBackdrop } from "@/components/layout/BrandArt";
import { BRAND } from "@/components/layout/brand";

const tabs = [
  { to: routes.documents, label: "Library" },
  { to: routes.dashboard, label: "Chat" },
];

export function AppShell() {
  const { theme, xaiPanelOpen, toggleXaiPanel } = useUI();
  const onChat = useMatch(routes.dashboard) !== null;
  return (
    // The shell fills the viewport and only <main> scrolls, so the header stays put on every page.
    // The navy header spans the full width; on Chat the Cases sidebar sits below it on the left.
    <div data-theme={theme} style={{ background: "var(--bg)", color: "var(--text)", height: "100vh", overflow: "hidden",
                                     display: "flex", flexDirection: "column" }}>
      {/* ── Top bar: crest and name, Library / Chat, Explain ── */}
      <header className="slaf-chrome slaf-header">
        <HeaderArt />

        <div className="slaf-brand">
          <BrandImage src={BRAND.crest} alt="Sri Lanka Air Force crest" className="slaf-brand-crest" />
          <div className="slaf-brand-text">
            <span className="slaf-brand-name">{BRAND.name}</span>
            <span className="slaf-brand-product">
              <span className="slaf-brand-system">{BRAND.system}</span>
              <span className="slaf-brand-sep" aria-hidden>|</span>
              {BRAND.product}
            </span>
          </div>
        </div>

        <nav className="slaf-tabs" aria-label="Main">
          {tabs.map((t) => (
            <NavLink key={t.to} to={t.to}
                     className={({ isActive }) => "slaf-tab" + (isActive ? " slaf-tab-active" : "")}>
              {t.label}
            </NavLink>
          ))}
        </nav>

        {/* Right-side action: the Explainability panel (Chat only) */}
        <div className="slaf-header-actions">
          {onChat && (
            <button
              id="xai-toggle-btn"
              type="button"
              className="slaf-explain"
              onClick={toggleXaiPanel}
              aria-pressed={xaiPanelOpen}
              aria-label={xaiPanelOpen ? "Hide explainability" : "Show explainability"}
              title={xaiPanelOpen ? "Hide explainability" : "Show explainability"}
            >
              <Sparkles size={16} strokeWidth={1.7} />
              Explain
            </button>
          )}
        </div>
      </header>

      {/* ── Sidebar (Chat), page and Explainability panel, below the top bar ── */}
      <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
        {onChat && <CasesSidebar />}
        <div className="slaf-stage">
          <SkyBackdrop />
          <main className="thin-scroll" style={{
            flex: 1,
            minWidth: 0,
            minHeight: 0,
            overflowY: "auto",
            display: "flex",
            flexDirection: "column",
            position: "relative",
          }}>
            <Outlet />
          </main>

          {onChat && <XaiPanel />}
        </div>
      </div>
    </div>
  );
}
