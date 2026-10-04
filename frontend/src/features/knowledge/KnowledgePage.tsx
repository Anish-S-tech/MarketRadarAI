import { useQuery } from "@tanstack/react-query";
import { BookOpenText, Search } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, call } from "@/api/client";
import { RelationshipGraph } from "@/components/RelationshipGraph";
import { Badge } from "@/components/ui/badges";
import { Button, Card, CardBody, CardHeader, EmptyState, Input, PageHeader, PageLoader, Select } from "@/components/ui/primitives";
import { timeAgo, titleCase } from "@/lib/format";

export function KnowledgePage() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const competitorId = params.get("competitor_id") ?? "";
  const [draft, setDraft] = useState(q);
  const competitors = useQuery({ queryKey: ["competitors"], queryFn: () => call(api.GET("/api/v1/competitors")) });
  const names = Object.fromEntries((competitors.data ?? []).map((c) => [c.id, c.name]));
  const hits = useQuery({
    queryKey: ["knowledge", q, competitorId],
    queryFn: () =>
      call(api.GET("/api/v1/knowledge/search", { params: { query: { q, competitor_id: competitorId || undefined, limit: 25 } } })),
    enabled: q.length >= 2,
  });
  const graph = useQuery({ queryKey: ["relationship-graph"], queryFn: () => call(api.GET("/api/v1/relationship-graph")) });

  return (
    <>
      <PageHeader title="Knowledge base" subtitle="Semantic + keyword search across the competitive memory" />
      <Card className="mb-5 p-3">
        <form
          className="flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const next = new URLSearchParams(params);
            next.set("q", draft);
            setParams(next);
          }}
        >
          <div className="relative min-w-60 flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-subtle" />
            <Input className="pl-8" placeholder="e.g. who raised prices on mid-market plans?" value={draft} onChange={(e) => setDraft(e.target.value)} />
          </div>
          <Select
            className="w-auto"
            value={competitorId}
            onChange={(e) => {
              const next = new URLSearchParams(params);
              if (e.target.value) next.set("competitor_id", e.target.value);
              else next.delete("competitor_id");
              setParams(next);
            }}
            aria-label="Competitor"
          >
            <option value="">All competitors</option>
            {competitors.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
          <Button type="submit" variant="primary">
            Search
          </Button>
        </form>
      </Card>

      {q.length >= 2 && (
        <Card className="mb-5">
          <CardHeader title={`Results for “${q}”`} subtitle={hits.data ? `${hits.data.length} matches` : undefined} />
          {hits.isLoading ? (
            <PageLoader />
          ) : hits.data?.length ? (
            <ul className="divide-y divide-default">
              {hits.data.map((h) => {
                const link = h.kind === "event" && h.ref_id ? `/events/${h.ref_id}` : h.kind === "evidence" ? `/events/${(h.meta as { event_id?: string }).event_id}` : null;
                return (
                  <li key={h.id} className="px-5 py-3">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge>{titleCase(h.kind)}</Badge>
                      {h.competitor_id && <span className="text-xs font-medium">{names[h.competitor_id]}</span>}
                      {h.similarity != null && <span className="text-xs text-subtle">similarity {h.similarity.toFixed(2)}</span>}
                      <span className="ml-auto text-xs text-subtle">{timeAgo(h.occurred_at)}</span>
                    </div>
                    {link ? (
                      <Link to={link} className="mt-1 block text-sm font-medium hover:underline">
                        {h.title}
                      </Link>
                    ) : (
                      <p className="mt-1 text-sm font-medium">{h.title}</p>
                    )}
                    <p className="mt-0.5 line-clamp-3 text-sm text-muted">{h.content}</p>
                  </li>
                );
              })}
            </ul>
          ) : (
            <EmptyState icon={<BookOpenText className="size-8" />} title="Nothing found" />
          )}
        </Card>
      )}

      <Card>
        <CardHeader title="Relationship map" subtitle="Us, our competitors, and the organisations around them" />
        <CardBody>{graph.data ? <RelationshipGraph graph={graph.data} /> : <PageLoader />}</CardBody>
      </Card>
    </>
  );
}
