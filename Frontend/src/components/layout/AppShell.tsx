import { NavLink, Outlet } from "react-router-dom";
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

        {/* Right-side actions: XAI button + User Avatar */}
        <div style={{
          position: "absolute",
          right: "24px",
          top: "50%",
          transform: "translateY(-50%)",
          display: "flex",
          alignItems: "center",
          gap: "10px",
        }}>
          {/* XAI Inspector Button */}
          <button
            id="xai-toggle-btn"
            onClick={toggleXaiPanel}
            title="XAI Inspector"
            style={{
              width: "32px",
              height: "32px",
              borderRadius: "50%",
              border: xaiPanelOpen
                ? "1.5px solid var(--primary)"
                : "1.5px solid var(--border)",
              background: xaiPanelOpen
                ? "var(--accent-bg)"
                : "transparent",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: "pointer",
              transition: "all 0.2s ease",
              position: "relative",
            }}
            onMouseEnter={(e) => {
              if (!xaiPanelOpen) e.currentTarget.style.borderColor = "var(--text-muted)";
            }}
            onMouseLeave={(e) => {
              if (!xaiPanelOpen) e.currentTarget.style.borderColor = "var(--border)";
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
              stroke={xaiPanelOpen ? "var(--primary)" : "var(--text-muted)"}
              strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
            >
              <path d="M12 2a4 4 0 0 1 4 4c0 1.95-1.4 3.26-2.13 3.76A1.87 1.87 0 0 0 13 11.4V12h-2v-.6a1.87 1.87 0 0 0-.87-1.64C9.4 9.26 8 7.95 8 6a4 4 0 0 1 4-4z" />
              <path d="M10 15h4" />
              <path d="M10 18h4" />
              <path d="M11 21h2" />
            </svg>
          </button>

          {/* User Avatar */}
          <div style={{
            width: "32px",
            height: "32px",
            borderRadius: "50%",
            border: "1.5px solid var(--border)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: "pointer",
          }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
              <circle cx="12" cy="7" r="4" />
            </svg>
          </div>
        </div>
      </header>

      {/* ── Main Content (shrinks when XAI panel is open) ── */}
      <main style={{
        flex: 1,
        minHeight: 0,
        overflowY: "auto",
        display: "flex",
        flexDirection: "column",
        marginRight: xaiPanelOpen ? "392px" : "0", // the floating XAI card + its gap
        transition: "margin-right 0.25s ease",
      }}>
        <Outlet />
      </main>

      {/* ── XAI Side Panel ── */}
      <XaiPanel />
    </div>
  );
}
