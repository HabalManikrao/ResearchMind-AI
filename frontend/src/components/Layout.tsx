import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  Brain,
  LayoutDashboard,
  Plus,
  History,
  Search,
  Activity,
  LogOut,
  CalendarClock,
  Bell,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { api } from "../api/client";
import { useHealth } from "../hooks/useHealth";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/new", label: "New Research", icon: Plus, end: false },
  { to: "/history", label: "History", icon: History, end: false },
  { to: "/scheduled", label: "Scheduled", icon: CalendarClock, end: false },
  { to: "/knowledge", label: "Knowledge Base", icon: Search, end: false },
  { to: "/notifications", label: "Notifications", icon: Bell, end: false, badge: true },
  { to: "/monitoring", label: "Monitoring", icon: Activity, end: false },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [unread, setUnread] = useState(0);
  const { health, error: healthError } = useHealth();

  // Worst-case readiness for the sidebar dot: red = backend down or Ollama down,
  // amber = search/embeddings not ready, green = all good.
  const dot = healthError || !health
    ? { color: "bg-red-500", label: "Backend unreachable" }
    : !health.llm.reachable
    ? { color: "bg-red-500", label: "Ollama unreachable" }
    : !health.search.configured
    ? { color: "bg-amber-400", label: `Search (${health.search.provider}) not ready` }
    : { color: "bg-emerald-500", label: "All systems ready" };

  // Poll the unread notification count so the sidebar badge stays fresh.
  useEffect(() => {
    let alive = true;
    const tick = () =>
      api
        .unreadCount()
        .then((r) => alive && setUnread(r.unread))
        .catch(() => {});
    tick();
    const id = setInterval(tick, 30000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const handleLogout = () => {
    logout();
    nav("/login", { replace: true });
  };

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-60 flex-col border-r border-slate-800 bg-slate-900 text-slate-300">
        <div className="flex items-center gap-2 px-5 py-5 text-white">
          <Brain className="h-6 w-6 text-brand-400" />
          <div>
            <div className="font-bold leading-tight">ResearchMind</div>
            <div className="text-xs text-slate-400">AI R&D Agent</div>
          </div>
        </div>
        <nav className="flex-1 space-y-1 px-3">
          {NAV.map(({ to, label, icon: Icon, end, badge }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
                  isActive
                    ? "bg-brand-600 text-white"
                    : "text-slate-300 hover:bg-slate-800 hover:text-white"
                }`
              }
            >
              <Icon className="h-4 w-4" />
              <span className="flex-1">{label}</span>
              {badge && unread > 0 && (
                <span className="rounded-full bg-red-500 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                  {unread > 99 ? "99+" : unread}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-800 px-3 py-3">
          <div className="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5">
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-white">
                {user?.name || user?.email || "Account"}
              </div>
              {user?.name && (
                <div className="truncate text-xs text-slate-400">{user.email}</div>
              )}
            </div>
            <button
              onClick={handleLogout}
              title="Sign out"
              className="rounded-md p-1.5 text-slate-400 transition hover:bg-slate-800 hover:text-white"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
          <div
            className="flex items-center gap-2 px-2 pt-2 text-xs text-slate-500"
            title={dot.label}
          >
            <span className={`h-2 w-2 rounded-full ${dot.color}`} />
            <span>v0.1.0 · {dot.label}</span>
          </div>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl px-8 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
