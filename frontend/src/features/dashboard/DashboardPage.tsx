import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  BellRing,
  Bot,
  ChevronRight,
  GitCompareArrows,
  Newspaper,
  Radar,
  Rss,
  Search,
  ShieldCheck,
  Siren,
  Target,
  Zap,
} from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, call } from "@/api/client";
import { PRIORITY_CHART } from "@/components/ui/badges";
import { Markdown } from "@/components/ui/Markdown";
import { Card, CardBody, CardHeader, EmptyState, PageHeader, PageLoader, Stat } from "@/components/ui/primitives";
import { EventRow } from "@/features/events/EventRow";
import { useAuth } from "@/lib/auth";
import { timeAgo, titleCase } from "@/lib/format";

const tooltipStyle = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  fontSize: 12,
  color: "var(--text)",
};

/** The six agents as a live pipeline strip, each with the metric it is responsible for. */
function AgentPipeline({ sources, checks, events, urgent }: { sources: number; checks: number; events: number; urgent: number }) {
  const steps: { icon: ReactNode; name: string; metric: string }[] = [
    { icon: <Radar className="size-4" />, name: "Scout", metric: `${sources} sources watched` },
    { icon: <GitCompareArrows className="size-4" />, name: "Detection", metric: `${checks} checks today` },
    { icon: <Search className="size-4" />, name: "Research", metric: `${events} investigated` },
    { icon: <ShieldCheck className="size-4" />, name: "Verification", metric: "evidence scored" },
    { icon: <Target className="size-4" />, name: "Impact", metric: "per-role analysis" },
    { icon: <BellRing className="size-4" />, name: "Alert", metric: `${urgent} urgent` },
  ];
  return (
    <Card className="mt-5 overflow-hidden">
      <div className="flex items-center gap-2 border-b border-default px-5 py-2.5">
        <span className="relative flex size-2">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-60" />
          <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
        </span>
        <p className="text-xs font-medium text-muted">Agents running autonomously</p>
      </div>
      <ol className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
        {steps.map((st, i) => (
          <li key={st.name} className="relative flex items-center gap-2.5 border-default px-4 py-3 not-last:lg:border-r">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-300">
              {st.icon}
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{st.name}</p>
              <p className="truncate text-xs text-subtle">{st.metric}</p>
            </div>
            {i < steps.length - 1 && (
              <ChevronRight className="absolute -right-2 top-1/2 z-10 hidden size-4 -translate-y-1/2 rounded-full bg-surface text-subtle lg:block" />
            )}
          </li>
        ))}
      </ol>
    </Card>
  );
}

export function DashboardPage() {
  const { user } = useAuth();
  const stats = useQuery({
    queryKey: ["stats", 14],
    queryFn: () => call(api.GET("/api/v1/events/stats", { params: { query: { days: 14 } } })),
    refetchInterval: 60_000,
  });
  const events = useQuery({
    queryKey: ["events", "feed"],
    queryFn: () => call(api.GET("/api/v1/events", { params: { query: { limit: 12 } } })),
    refetchInterval: 60_000,
  });
  const brief = useQuery({ queryKey: ["briefs", "latest"], queryFn: () => call(api.GET("/api/v1/briefs/latest")) });

  if (stats.isLoading) return <PageLoader />;
  const s = stats.data;
  const urgent = (s?.by_priority.critical ?? 0) + (s?.by_priority.high ?? 0);
  const runsOk = (s?.runs_24h.succeeded ?? 0) + (s?.runs_24h.skipped ?? 0);
  const runsBad = (s?.runs_24h.failed ?? 0) + (s?.runs_24h.dead_letter ?? 0);

  return (
    <>
      <PageHeader
        title={`Good ${new Date().getHours() < 12 ? "morning" : new Date().getHours() < 18 ? "afternoon" : "evening"}${user?.full_name ? `, ${user.full_name.split(" ")[0]}` : ""}`}
        subtitle="What your competitors did while the agents were watching"
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          icon={<Zap className="size-4.5" />}
          label="Events · 14 days"
          value={s?.total ?? 0}
          hint={`${Object.keys(s?.by_category ?? {}).length} categories`}
        />
        <Stat
          icon={<Siren className="size-4.5" />}
          tone="red"
          label="Critical + high"
          value={urgent}
          accent={urgent ? "text-red-600 dark:text-red-400" : undefined}
          hint={`${s?.by_priority.critical ?? 0} critical`}
        />
        <Stat
          icon={<Rss className="size-4.5" />}
          tone={s?.sources_failing ? "amber" : "indigo"}
          label="Sources monitored"
          value={s?.sources_active ?? 0}
          hint={s?.sources_failing ? `${s.sources_failing} failing` : "all healthy"}
        />
        <Stat
          icon={<Bot className="size-4.5" />}
          tone={runsBad ? "amber" : "brand"}
          label="Agent runs · 24h"
          value={runsOk + runsBad}
          hint={runsBad ? `${runsBad} failed` : "no failures"}
        />
      </div>

      <AgentPipeline sources={s?.sources_active ?? 0} checks={runsOk + runsBad} events={s?.total ?? 0} urgent={urgent} />

      <div className="mt-5 grid gap-5 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader
            title="Priority feed"
            subtitle="Newest verified events"
            actions={
              <Link to="/events" className="inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:underline dark:text-brand-300">
                All events <ArrowRight className="size-3" />
              </Link>
            }
          />
          {events.data?.items.length ? (
            <div className="divide-y divide-default">
              {events.data.items.map((e) => (
                <EventRow key={e.id} event={e} />
              ))}
            </div>
          ) : (
            <EmptyState icon={<Radar className="size-8" />} title="No events yet">
              The agents are monitoring your sources. Significant changes will appear here automatically.
            </EmptyState>
          )}
        </Card>

        <div className="space-y-5 lg:col-span-2">
          <Card>
            <CardHeader title="Events per day" subtitle="Last 14 days, by priority" />
            <CardBody className="h-56 pt-2">
              {s?.daily.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={s.daily} margin={{ left: -24, right: 4, top: 4 }}>
                    <CartesianGrid vertical={false} stroke="var(--border)" />
                    <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(5)} tick={{ fontSize: 11, fill: "var(--text-subtle)" }} axisLine={false} tickLine={false} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "var(--text-subtle)" }} axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "var(--surface-sunken)" }} />
                    <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} formatter={(v: string) => titleCase(v)} />
                    {(["low", "medium", "high", "critical"] as const).map((p) => (
                      <Bar key={p} dataKey={p} stackId="a" fill={PRIORITY_CHART[p]} maxBarSize={28} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <EmptyState title="No data yet" />
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Most active competitors" subtitle="Events in the last 14 days" />
            <CardBody className="space-y-2.5">
              {s?.by_competitor.length ? (
                s.by_competitor.slice(0, 6).map((c) => {
                  const max = s.by_competitor[0].count as number;
                  return (
                    <Link key={c.competitor_id as string} to={`/competitors/${c.competitor_id}`} className="block">
                      <div className="flex justify-between text-sm">
                        <span className="font-medium hover:underline">{c.name as string}</span>
                        <span className="tabular-nums text-muted">{c.count as number}</span>
                      </div>
                      <div className="mt-1 h-1.5 rounded-full bg-surface-sunken">
                        <div className="h-1.5 rounded-full bg-brand-500" style={{ width: `${((c.count as number) / max) * 100}%` }} />
                      </div>
                    </Link>
                  );
                })
              ) : (
                <p className="text-sm text-muted">No activity yet.</p>
              )}
            </CardBody>
          </Card>
        </div>
      </div>

      <Card className="mt-5">
        <CardHeader
          title={
            <span className="inline-flex items-center gap-2">
              <Newspaper className="size-4 text-brand-600" /> Latest daily brief
            </span>
          }
          subtitle={brief.data ? `${brief.data.brief_date} · ${titleCase(brief.data.role)} edition · generated ${timeAgo(brief.data.generated_at)}` : undefined}
          actions={
            brief.data && (
              <Link to={`/briefs/${brief.data.id}`} className="text-xs font-medium text-brand-700 hover:underline dark:text-brand-300">
                Open brief
              </Link>
            )
          }
        />
        <CardBody>
          {brief.data ? (
            <Markdown className="line-clamp-[12]">{brief.data.content_md.split("\n## ")[0]}</Markdown>
          ) : (
            <p className="text-sm text-muted">Daily briefs are generated automatically each morning.</p>
          )}
        </CardBody>
      </Card>
    </>
  );
}
