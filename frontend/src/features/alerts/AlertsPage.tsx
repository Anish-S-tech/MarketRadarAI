import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, CheckCheck, ExternalLink } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, call, type AlertOut } from "@/api/client";
import { PriorityBadge } from "@/components/ui/badges";
import { Markdown } from "@/components/ui/Markdown";
import { Button, Card, EmptyState, PageHeader, PageLoader, Tabs } from "@/components/ui/primitives";
import { cn, timeAgo } from "@/lib/format";

export function AlertsPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<"unread" | "all">("unread");
  const [open, setOpen] = useState<string | null>(null);
  const alerts = useQuery({
    queryKey: ["alerts", "list", filter],
    queryFn: () => call(api.GET("/api/v1/alerts", { params: { query: { unread_only: filter === "unread", limit: 100 } } })),
  });
  const read = useMutation({
    mutationFn: (id: string) => call(api.POST("/api/v1/alerts/{alert_id}/read", { params: { path: { alert_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });
  const readAll = useMutation({
    mutationFn: () => call(api.POST("/api/v1/alerts/read-all")),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });

  const expand = (a: AlertOut) => {
    setOpen(open === a.id ? null : a.id);
    if (!a.read_at) read.mutate(a.id);
  };

  return (
    <>
      <PageHeader
        title="Alerts"
        subtitle="Role-specific alerts routed to you by the Alert Agent"
        actions={
          <Button icon={<CheckCheck className="size-4" />} onClick={() => readAll.mutate()} loading={readAll.isPending}>
            Mark all read
          </Button>
        }
      />
      <Tabs
        tabs={[
          { id: "unread", label: "Unread" },
          { id: "all", label: "All" },
        ]}
        value={filter}
        onChange={setFilter}
      />
      <Card className="mt-4">
        {alerts.isLoading ? (
          <PageLoader />
        ) : alerts.data?.items.length ? (
          <ul className="divide-y divide-default">
            {alerts.data.items.map((a) => (
              <li key={a.id}>
                <button onClick={() => expand(a)} className="flex w-full items-start gap-3 px-5 py-3 text-left hover:bg-surface-sunken/60">
                  <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", a.read_at ? "bg-transparent" : "bg-brand-500")} />
                  <div className="min-w-0 flex-1">
                    <p className={cn("text-sm", a.read_at ? "text-muted" : "font-medium")}>{a.title}</p>
                    <p className="text-xs text-subtle">{timeAgo(a.created_at)}</p>
                  </div>
                  <PriorityBadge priority={a.priority} />
                </button>
                {open === a.id && (
                  <div className="border-t border-default bg-surface-sunken/40 px-5 py-4 sm:pl-10">
                    <Markdown>{a.body_md}</Markdown>
                    <Link to={`/events/${a.event_id}`} className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline dark:text-brand-300">
                      Open event <ExternalLink className="size-3.5" />
                    </Link>
                  </div>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState icon={<Bell className="size-8" />} title={filter === "unread" ? "You're all caught up" : "No alerts yet"} />
        )}
      </Card>
    </>
  );
}
