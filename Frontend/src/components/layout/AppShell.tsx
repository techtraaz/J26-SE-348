import { NavLink, Outlet } from "react-router-dom";
import { Sparkles } from "lucide-react";
import { useUI } from "@/store/ui";
import { routes } from "@/config/routes";
import { XaiPanel } from "@/components/ui/XaiPanel";

const tabs = [
  { to: routes.documents, label: "Library" },
  { to: routes.dashboard, label: "Chat" },
];

export function AppShell() {
  const { theme, xaiPanelOpen, toggleXaiPanel } = useUI();
  return (
    // The shell fills the viewport and only <main> scrolls, so the header stays put on every page.
    <div data-theme={theme} style={{ background: "var(--bg)", color: "var(--text)", height: "100vh", overflow: "hidden", display: "flex", flexDirection: "column" }}>
      {/* ── Top Navigation Bar ── */}
      <header style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "14px 24px",
        position: "relative",
        flexShrink: 0,
        borderBottom: "1px solid var(--border-light)",
      }}>
        {/* Center Tabs */}
        <nav style={{ display: "flex", alignItems: "center", gap: "4px" }}>
          {tabs.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              className={({ isActive }) => "nav-tab" + (isActive ? " nav-tab-active" : "")}
              style={({ isActive }) => ({
                padding: "7px 20px",
                borderRadius: "999px",
                fontSize: "14px",
                fontWeight: 500,
                textDecoration: "none",
                transition: "all 0.2s ease",
                color: isActive ? "var(--text-h)" : "var(--text-muted)",
                background: isActive ? "var(--tab-active-bg)" : "transparent",
                border: isActive ? "1px solid var(--tab-active-border)" : "1px solid transparent",
              })}
            >
              {t.label}
            </NavLink>
          ))}
        </nav>

        {/* Right-side action: the Explainability panel */}
        <div style={{
          position: "absolute",
          right: "24px",
          top: "50%",
          transform: "translateY(-50%)",
        }}>
          <button
            id="xai-toggle-btn"
            type="button"
            className="icon-btn"
            onClick={toggleXaiPanel}
            aria-pressed={xaiPanelOpen}
            aria-label={xaiPanelOpen ? "Hide explainability" : "Show explainability"}
            data-tip={xaiPanelOpen ? "Hide explainability" : "Show explainability"}
            data-tip-side="bottom-end"
            style={{
              height: "34px",
              padding: "0 12px",
              borderRadius: "10px",
              border: "1px solid " + (xaiPanelOpen ? "var(--border-strong)" : "transparent"),
              background: xaiPanelOpen ? "var(--sidebar-active)" : "transparent",
              color: xaiPanelOpen ? "var(--text-h)" : "var(--text-muted)",
              display: "flex",
              alignItems: "center",
              gap: "7px",
              cursor: "pointer",
              fontFamily: "inherit",
              fontSize: "13px",
              fontWeight: 500,
            }}
          >
            <Sparkles size={16} strokeWidth={1.6} />
            Explain
          </button>
        </div>
      </header>

      {/* ── Page + Explainability panel, side by side below the header ── */}
      <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
        <main style={{
          flex: 1,
          minWidth: 0,
          minHeight: 0,
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
        }}>
          <Outlet />
        </main>

        <XaiPanel />
      </div>
    </div>
  );
}
