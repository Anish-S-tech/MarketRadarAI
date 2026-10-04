import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { PageLoader } from "./components/ui/primitives";
import { LoginPage, OidcCallback, RegisterPage } from "./features/auth/AuthPages";
import { useAuth } from "./lib/auth";

// Route-level code splitting: charts (Recharts) and graphs (React Flow) load only where used.
const page = <K extends string>(load: () => Promise<Record<K, React.ComponentType>>, name: K) =>
  lazy(() => load().then((m) => ({ default: m[name] })));

const DashboardPage = page(() => import("./features/dashboard/DashboardPage"), "DashboardPage");
const EventsPage = page(() => import("./features/events/EventsPage"), "EventsPage");
const EventDetailPage = page(() => import("./features/events/EventDetailPage"), "EventDetailPage");
const CompetitorsPage = page(() => import("./features/competitors/CompetitorsPage"), "CompetitorsPage");
const CompetitorPage = page(() => import("./features/competitors/CompetitorPage"), "CompetitorPage");
const SourcesPage = page(() => import("./features/sources/SourcesPage"), "SourcesPage");
const AlertsPage = page(() => import("./features/alerts/AlertsPage"), "AlertsPage");
const BriefsPage = page(() => import("./features/briefs/BriefsPage"), "BriefsPage");
const KnowledgePage = page(() => import("./features/knowledge/KnowledgePage"), "KnowledgePage");
const RunsPage = page(() => import("./features/runs/RunsPage"), "RunsPage");
const SettingsPage = page(() => import("./features/settings/SettingsPage"), "SettingsPage");

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <PageLoader />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

const lazyEl = (el: ReactNode) => <Suspense fallback={<PageLoader />}>{el}</Suspense>;

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/auth/callback" element={<OidcCallback />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={lazyEl(<DashboardPage />)} />
        <Route path="events" element={lazyEl(<EventsPage />)} />
        <Route path="events/:id" element={lazyEl(<EventDetailPage />)} />
        <Route path="competitors" element={lazyEl(<CompetitorsPage />)} />
        <Route path="competitors/:id" element={lazyEl(<CompetitorPage />)} />
        <Route path="sources" element={lazyEl(<SourcesPage />)} />
        <Route path="alerts" element={lazyEl(<AlertsPage />)} />
        <Route path="briefs" element={lazyEl(<BriefsPage />)} />
        <Route path="briefs/:id" element={lazyEl(<BriefsPage />)} />
        <Route path="knowledge" element={lazyEl(<KnowledgePage />)} />
        <Route path="runs" element={lazyEl(<RunsPage />)} />
        <Route path="settings" element={lazyEl(<SettingsPage />)} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
