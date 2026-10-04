import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Search, Zap } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, call } from "@/api/client";
import { Button, Card, EmptyState, Input, PageHeader, PageLoader, Select } from "@/components/ui/primitives";
import { CATEGORIES, PRIORITIES, cn, titleCase } from "@/lib/format";
import { EventRow } from "./EventRow";

const PAGE = 25;

export function EventsPage() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const priority = params.getAll("priority");
  const category = params.get("category") ?? "";
  const competitorId = params.get("competitor_id") ?? "";
  const status = params.get("status") ?? "";
  const offset = Number(params.get("offset") ?? 0);

  const competitors = useQuery({ queryKey: ["competitors"], queryFn: () => call(api.GET("/api/v1/competitors")) });
  const events = useQuery({
    queryKey: ["events", "list", params.toString()],
    queryFn: () =>
      call(
        api.GET("/api/v1/events", {
          params: {
            query: {
              priority: priority.length ? priority : undefined,
              category: category ? [category] : undefined,
              competitor_id: competitorId || undefined,
              status: status || undefined,
              q: params.get("q") || undefined,
              limit: PAGE,
              offset,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });

  const update = (k: string, v: string | string[] | null) => {
    const next = new URLSearchParams(params);
    next.delete(k);
    next.delete("offset");
    if (Array.isArray(v)) v.forEach((x) => next.append(k, x));
    else if (v) next.set(k, v);
    setParams(next);
  };

  const togglePriority = (p: string) =>
    update("priority", priority.includes(p) ? priority.filter((x) => x !== p) : [...priority, p]);

  return (
    <>
      <PageHeader title="Events" subtitle="Every verified competitive development, prioritised" />
      <Card className="mb-4 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <form
            className="relative min-w-52 flex-1"
            onSubmit={(e) => {
              e.preventDefault();
              update("q", q);
            }}
          >
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-subtle" />
            <Input placeholder="Search titles and summaries…" value={q} onChange={(e) => setQ(e.target.value)} className="pl-8" />
          </form>
          <div className="flex gap-1" role="group" aria-label="Priority filter">
            {PRIORITIES.map((p) => (
              <button
                key={p}
                onClick={() => togglePriority(p)}
                className={cn(
                  "h-9 rounded-lg border px-2.5 text-xs font-medium",
                  priority.includes(p)
                    ? "border-brand-600 bg-brand-50 text-brand-800 dark:bg-brand-500/10 dark:text-brand-200"
                    : "border-default text-muted hover:bg-surface-sunken",
                )}
              >
                {titleCase(p)}
              </button>
            ))}
          </div>
          <Select value={category} onChange={(e) => update("category", e.target.value)} className="w-auto" aria-label="Category">
            <option value="">All categories</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {titleCase(c)}
              </option>
            ))}
          </Select>
          <Select value={competitorId} onChange={(e) => update("competitor_id", e.target.value)} className="w-auto" aria-label="Competitor">
            <option value="">All competitors</option>
            {competitors.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
          <Select value={status} onChange={(e) => update("status", e.target.value)} className="w-auto" aria-label="Status">
            <option value="">Any status</option>
            {["new", "acknowledged", "actioned", "dismissed"].map((s) => (
              <option key={s} value={s}>
                {titleCase(s)}
              </option>
            ))}
          </Select>
        </div>
      </Card>

      <Card>
        {events.isLoading ? (
          <PageLoader />
        ) : events.data?.items.length ? (
          <>
            <div className="divide-y divide-default">
              {events.data.items.map((e) => (
                <EventRow key={e.id} event={e} />
              ))}
            </div>
            <div className="flex items-center justify-between border-t border-default px-5 py-3 text-xs text-muted">
              <span>
                {offset + 1}–{Math.min(offset + PAGE, events.data.total)} of {events.data.total}
              </span>
              <div className="flex gap-2">
                <Button size="sm" disabled={offset === 0} onClick={() => update("offset", String(Math.max(0, offset - PAGE)))}>
                  Previous
                </Button>
                <Button size="sm" disabled={offset + PAGE >= events.data.total} onClick={() => update("offset", String(offset + PAGE))}>
                  Next
                </Button>
              </div>
            </div>
          </>
        ) : (
          <EmptyState icon={<Zap className="size-8" />} title="No events match these filters" />
        )}
      </Card>
    </>
  );
}
