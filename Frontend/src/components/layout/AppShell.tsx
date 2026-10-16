import { NavLink, Outlet } from "react-router-dom";
import { useUI } from "@/store/ui";
import { routes } from "@/config/routes";

const links = [
  { to: routes.dashboard, label: "Dashboard" },
  { to: routes.cases, label: "Cases" },
  { to: routes.documents, label: "Documents" },
  { to: routes.findings, label: "Findings" },
  { to: routes.policies, label: "Policies" },
  { to: routes.reports, label: "Reports" },
  { to: routes.settings, label: "Settings" },
];

export function AppShell() {
  const { theme, toggleTheme, selectedCase } = useUI();
  return (
    <div data-theme={theme} className="flex min-h-screen bg-[var(--bg)] text-[var(--text)]">
      <aside className="w-60 shrink-0 bg-[var(--nav)] p-4 text-white">
        <div className="mb-4 font-extrabold tracking-widest">NOMOS</div>
        <nav className="flex flex-col gap-1">
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} className={({ isActive }) => `rounded-lg px-3 py-2 text-sm ${isActive ? "bg-[var(--primary)]" : "hover:bg-white/10"}`}>
              {l.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface)] px-5 py-3">
          <div><strong>Case: {selectedCase}</strong><span className="ml-2 rounded-full border px-2 py-0.5 text-xs">pending_review</span></div>
          <button onClick={toggleTheme} className="rounded-lg border px-3 py-1 text-sm">Theme: {theme}</button>
        </header>
        <main className="mx-auto w-full max-w-6xl p-5"><Outlet /></main>
      </div>
    </div>
  );
}
