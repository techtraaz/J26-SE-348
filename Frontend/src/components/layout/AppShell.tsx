import { NavLink, Outlet } from "react-router-dom";
import { useUI } from "@/store/ui";
import { routes } from "@/config/routes";

const tabs = [
  { to: routes.documents, label: "Library" },
  { to: routes.dashboard, label: "Chat" },
];

export function AppShell() {
  const { theme } = useUI();
  return (
    <div data-theme={theme} style={{ background: "var(--bg)", color: "var(--text)", minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      {/* ── Top Navigation Bar ── */}
      <header style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "14px 24px",
        position: "relative",
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

        {/* User Avatar */}
        <div style={{
          position: "absolute",
          right: "24px",
          top: "50%",
          transform: "translateY(-50%)",
        }}>
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

      {/* ── Main Content ── */}
      <main style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        <Outlet />
      </main>
    </div>
  );
}
