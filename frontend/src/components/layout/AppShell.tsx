import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Bell,
  BookOpenText,
  Building2,
  LayoutDashboard,
  LogOut,
  Menu,
  Monitor,
  Moon,
  Newspaper,
  Radar,
  Rss,
  Search,
  Settings,
  Sun,
  Zap,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { api, call } from "@/api/client";
import { useAlertStream } from "@/hooks/useAlertStream";
import { useTheme } from "@/hooks/useTheme";
import { useAuth } from "@/lib/auth";
import { cn, titleCase } from "@/lib/format";

const NAV: { to: string; label: string; icon: ReactNode }[] = [
  { to: "/", label: "Dashboard", icon: <LayoutDashboard className="size-4" /> },
  { to: "/events", label: "Events", icon: <Zap className="size-4" /> },
  { to: "/competitors", label: "Competitors", icon: <Building2 className="size-4" /> },
  { to: "/sources", label: "Sources", icon: <Rss className="size-4" /> },
  { to: "/alerts", label: "Alerts", icon: <Bell className="size-4" /> },
  { to: "/briefs", label: "Daily briefs", icon: <Newspaper className="size-4" /> },
  { to: "/knowledge", label: "Knowledge", icon: <BookOpenText className="size-4" /> },
  { to: "/runs", label: "Agent runs", icon: <Activity className="size-4" /> },
  { to: "/settings", label: "Settings", icon: <Settings className="size-4" /> },
];

function UnreadCount() {
  const { data } = useQuery({
    queryKey: ["alerts", "unread-count"],
    queryFn: () => call(api.GET("/api/v1/alerts/unread-count")),
    refetchInterval: 60_000,
  });
  if (!data?.unread) return null;
  return (
    <span className="ml-auto rounded-full bg-red-500 px-1.5 py-px text-[10px] font-semibold text-white tabular-nums">
      {data.unread > 99 ? "99+" : data.unread}
    </span>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex flex-col gap-0.5 p-3" aria-label="Main">
      {NAV.map((n) => (
        <NavLink
          key={n.to}
          to={n.to}
          end={n.to === "/"}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm font-medium transition-colors",
              isActive
                ? "bg-brand-50 text-brand-800 dark:bg-brand-500/10 dark:text-brand-200"
                : "text-muted hover:bg-surface-sunken hover:text-default",
            )
          }
        >
          {n.icon}
          {n.label}
          {n.to === "/alerts" && <UnreadCount />}
        </NavLink>
      ))}
    </nav>
  );
}

export function AppShell() {
  const { user, logout } = useAuth();
  const { theme, cycle } = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);
  useAlertStream(!!user);

  const ThemeIcon = theme === "dark" ? Moon : theme === "light" ? Sun : Monitor;

  return (
    <div className="flex h-full">
      <aside className="bg-surface hidden w-60 shrink-0 flex-col border-r border-default md:flex">
        <Link to="/" className="flex h-14 items-center gap-2 border-b border-default px-4">
          <span className="flex size-7 items-center justify-center rounded-lg bg-brand-700 text-white">
            <Radar className="size-4" />
          </span>
          <span className="font-semibold tracking-tight">MarketRadar</span>
          <span className="rounded bg-brand-50 px-1 text-[10px] font-semibold text-brand-700 dark:bg-brand-500/10 dark:text-brand-300">
            AI
          </span>
        </Link>
        <div className="flex-1 overflow-y-auto">
          <Sidebar />
        </div>
        <div className="border-t border-default p-3">
          <div className="flex items-center gap-2 rounded-lg px-2 py-1.5">
            <div className="flex size-8 items-center justify-center rounded-full bg-surface-sunken text-xs font-semibold">
              {(user?.full_name || user?.email || "?").slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{user?.full_name || user?.email}</p>
              <p className="text-xs text-subtle">{user ? titleCase(user.role) : ""}</p>
            </div>
            <button onClick={cycle} className="rounded-md p-1.5 text-subtle hover:bg-surface-sunken" title={`Theme: ${theme}`} aria-label="Toggle theme">
              <ThemeIcon className="size-4" />
            </button>
            <button onClick={logout} className="rounded-md p-1.5 text-subtle hover:bg-surface-sunken" title="Sign out" aria-label="Sign out">
              <LogOut className="size-4" />
            </button>
          </div>
        </div>
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 bg-black/40 md:hidden" onClick={() => setMobileOpen(false)}>
          <aside className="bg-surface h-full w-64 border-r border-default" onClick={(e) => e.stopPropagation()}>
            <div className="flex h-14 items-center gap-2 border-b border-default px-4 font-semibold">
              <Radar className="size-4 text-brand-600" /> MarketRadar
            </div>
            <Sidebar onNavigate={() => setMobileOpen(false)} />
            <div className="border-t border-default p-3">
              <button onClick={logout} className="flex items-center gap-2 text-sm text-muted">
                <LogOut className="size-4" /> Sign out
              </button>
            </div>
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="bg-surface flex h-14 shrink-0 items-center gap-3 border-b border-default px-4 md:hidden">
          <button onClick={() => setMobileOpen(true)} aria-label="Open menu" className="rounded-md p-1.5 hover:bg-surface-sunken">
            <Menu className="size-5" />
          </button>
          <span className="font-semibold">MarketRadar</span>
          <div className="ml-auto flex items-center gap-1">
            <Link to="/knowledge" className="rounded-md p-1.5 hover:bg-surface-sunken" aria-label="Search">
              <Search className="size-4" />
            </Link>
            <button onClick={cycle} className="rounded-md p-1.5 hover:bg-surface-sunken" aria-label="Toggle theme">
              <ThemeIcon className="size-4" />
            </button>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
