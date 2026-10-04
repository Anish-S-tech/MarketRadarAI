import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, call, type CompetitorIn } from "@/api/client";
import { RelationshipGraph } from "@/components/RelationshipGraph";
import { Badge, ThreatTier } from "@/components/ui/badges";
import { Button, Card, CardBody, CardHeader, EmptyState, ErrorNote, Field, Input, Modal, PageLoader, Select, Tabs } from "@/components/ui/primitives";
import { EventRow } from "@/features/events/EventRow";
import { SourcesTable } from "@/features/sources/SourcesPage";
import { useAuth } from "@/lib/auth";
import { timeAgo, titleCase } from "@/lib/format";
import { CompetitorForm, Monogram } from "./CompetitorsPage";
import { PricingHistory } from "./PricingHistory";

type Tab = "overview" | "timeline" | "pricing" | "products" | "relationships" | "sources";
const REL_TYPES = ["partner", "investor", "acquirer", "acquired", "integration", "customer", "supplier", "competitor"] as const;

export function CompetitorPage() {
  const { id } = useParams() as { id: string };
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "overview";
  const { hasRole } = useAuth();
  const canEdit = hasRole("executive", "product", "marketing", "pricing");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const path = { params: { path: { competitor_id: id } } };

  const comp = useQuery({ queryKey: ["competitor", id], queryFn: () => call(api.GET("/api/v1/competitors/{competitor_id}", path)) });
  const timeline = useQuery({ queryKey: ["competitor", id, "timeline"], queryFn: () => call(api.GET("/api/v1/competitors/{competitor_id}/timeline", path)) });
  const pricing = useQuery({
    queryKey: ["competitor", id, "pricing"],
    queryFn: () => call(api.GET("/api/v1/competitors/{competitor_id}/pricing-history", path)),
    enabled: tab === "pricing" || tab === "overview",
  });
  const products = useQuery({
    queryKey: ["competitor", id, "products"],
    queryFn: () => call(api.GET("/api/v1/competitors/{competitor_id}/products", path)),
    enabled: tab === "products" || tab === "overview",
  });
  const rels = useQuery({
    queryKey: ["competitor", id, "relationships"],
    queryFn: () => call(api.GET("/api/v1/competitors/{competitor_id}/relationships", path)),
    enabled: tab === "relationships" || tab === "overview",
  });

  const [editing, setEditing] = useState(false);
  const update = useMutation({
    mutationFn: (body: CompetitorIn) => call(api.PATCH("/api/v1/competitors/{competitor_id}", { ...path, body })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["competitor", id] });
      qc.invalidateQueries({ queryKey: ["competitors"] });
      setEditing(false);
    },
  });
  const remove = useMutation({
    mutationFn: () => call(api.DELETE("/api/v1/competitors/{competitor_id}", path)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["competitors"] });
      navigate("/competitors");
    },
  });

  const [rel, setRel] = useState({ counterparty_name: "", rel_type: "partner" as (typeof REL_TYPES)[number], description: "" });
  const addRel = useMutation({
    mutationFn: () => call(api.POST("/api/v1/competitors/{competitor_id}/relationships", { ...path, body: rel })),
    onSuccess: () => {
      setRel({ counterparty_name: "", rel_type: "partner", description: "" });
      qc.invalidateQueries({ queryKey: ["competitor", id, "relationships"] });
    },
  });

  if (comp.isLoading) return <PageLoader />;
  if (!comp.data) return <ErrorNote error={comp.error ?? "Not found"} />;
  const c = comp.data;
  const graph = {
    nodes: [
      { id: c.id, label: c.name, kind: "competitor" },
      ...(rels.data ?? []).map((r) => ({ id: `org:${r.id}`, label: r.counterparty_name, kind: "organization" })),
    ],
    edges: (rels.data ?? []).map((r) => ({ id: r.id, source: c.id, target: `org:${r.id}`, label: r.rel_type })),
  };

  return (
    <>
      <Link to="/competitors" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-default">
        <ArrowLeft className="size-4" /> Competitors
      </Link>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3.5">
          <Monogram name={c.name} size="lg" />
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold tracking-tight">{c.name}</h1>
              <ThreatTier tier={c.threat_tier} />
            </div>
            <p className="mt-0.5 text-sm text-muted">
              {c.domain}
              {c.ticker && ` · ${c.ticker}`}
              {c.segments.length > 0 && ` · ${c.segments.join(", ")}`}
            </p>
          </div>
        </div>
        {canEdit && (
          <div className="flex gap-2">
            <Button size="sm" icon={<Pencil className="size-3.5" />} onClick={() => setEditing(true)}>
              Edit
            </Button>
            <Button
              size="sm"
              variant="ghost"
              icon={<Trash2 className="size-3.5" />}
              onClick={() => confirm(`Delete ${c.name} and all its history?`) && remove.mutate()}
            >
              Delete
            </Button>
          </div>
        )}
      </div>

      <Tabs<Tab>
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "timeline", label: `Timeline (${timeline.data?.length ?? 0})` },
          { id: "pricing", label: "Pricing" },
          { id: "products", label: "Products" },
          { id: "relationships", label: "Relationships" },
          { id: "sources", label: "Sources" },
        ]}
        value={tab}
        onChange={(t) => setParams({ tab: t })}
      />

      <div className="mt-5 space-y-5">
        {tab === "overview" && (
          <div className="grid gap-5 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader title="Profile" subtitle="Rolling summary maintained by the Knowledge agent" />
              <CardBody>
                <p className="text-sm leading-relaxed">{c.summary || c.description || "No profile yet — it builds up as events are detected."}</p>
                {c.summary && c.description && <p className="mt-3 text-sm text-muted">{c.description}</p>}
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="At a glance" />
              <CardBody className="space-y-2 text-sm">
                <div className="flex justify-between"><span className="text-muted">Events tracked</span><b>{timeline.data?.length ?? 0}</b></div>
                <div className="flex justify-between"><span className="text-muted">Current plans</span><b>{pricing.data?.filter((p) => !p.valid_to).length ?? 0}</b></div>
                <div className="flex justify-between"><span className="text-muted">Products known</span><b>{products.data?.length ?? 0}</b></div>
                <div className="flex justify-between"><span className="text-muted">Relationships</span><b>{rels.data?.length ?? 0}</b></div>
                <div className="flex justify-between"><span className="text-muted">Last event</span><b>{timeAgo(timeline.data?.[0]?.detected_at)}</b></div>
              </CardBody>
            </Card>
            <Card className="lg:col-span-3">
              <CardHeader title="Recent events" />
              {timeline.data?.length ? (
                <div className="divide-y divide-default">
                  {timeline.data.slice(0, 5).map((e) => <EventRow key={e.id} event={e} />)}
                </div>
              ) : (
                <EmptyState title="No events yet" />
              )}
            </Card>
          </div>
        )}

        {tab === "timeline" && (
          <Card>
            {timeline.data?.length ? (
              <ol className="relative ml-6 border-l border-default py-4">
                {timeline.data.map((e) => (
                  <li key={e.id} className="relative pb-1 pl-2">
                    <span className="absolute -left-[5px] top-5 size-2.5 rounded-full border-2 border-[var(--surface)] bg-brand-500" />
                    <p className="pl-3 text-xs text-subtle">{new Date(e.detected_at).toLocaleDateString(undefined, { dateStyle: "medium" })}</p>
                    <EventRow event={e} compact />
                  </li>
                ))}
              </ol>
            ) : (
              <EmptyState title="No events yet" />
            )}
          </Card>
        )}

        {tab === "pricing" && (
          <Card>
            <CardHeader title="Pricing history" subtitle="Every observed plan price, as captured from monitored pricing pages" />
            <CardBody>{pricing.isLoading ? <PageLoader /> : <PricingHistory points={pricing.data ?? []} />}</CardBody>
          </Card>
        )}

        {tab === "products" && (
          <div className="grid gap-4 md:grid-cols-2">
            {products.data?.length ? (
              products.data.map((p) => (
                <Card key={p.id} className="p-4">
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="font-semibold">{p.name}</h3>
                    {p.category && <Badge>{p.category}</Badge>}
                  </div>
                  <p className="mt-1 text-sm text-muted">{p.description}</p>
                  {p.features.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1">
                      {p.features.map((f) => <Badge key={f.id}>{f.name}</Badge>)}
                    </div>
                  )}
                  <p className="mt-3 text-xs text-subtle">First seen {timeAgo(p.first_seen_at)}</p>
                </Card>
              ))
            ) : (
              <Card className="md:col-span-2">
                <EmptyState title="No products extracted yet">Products and features are extracted automatically from product and launch events.</EmptyState>
              </Card>
            )}
          </div>
        )}

        {tab === "relationships" && (
          <div className="grid gap-5 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader title="Relationship map" subtitle="Partners, investors, acquisitions and integrations" />
              <CardBody>
                {rels.data?.length ? <RelationshipGraph graph={graph} height={360} /> : <EmptyState title="No relationships known yet" />}
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="Known relationships" />
              <CardBody className="space-y-3">
                {rels.data?.map((r) => (
                  <div key={r.id} className="text-sm">
                    <div className="flex items-center gap-2">
                      <Badge>{titleCase(r.rel_type)}</Badge>
                      <span className="font-medium">{r.counterparty_name}</span>
                    </div>
                    {r.description && <p className="mt-0.5 text-xs text-muted">{r.description}</p>}
                  </div>
                ))}
                {canEdit && (
                  <form
                    className="space-y-2 border-t border-default pt-3"
                    onSubmit={(e) => {
                      e.preventDefault();
                      addRel.mutate();
                    }}
                  >
                    <Field label="Add relationship">
                      <Input placeholder="Organisation name" required value={rel.counterparty_name} onChange={(e) => setRel({ ...rel, counterparty_name: e.target.value })} />
                    </Field>
                    <Select value={rel.rel_type} onChange={(e) => setRel({ ...rel, rel_type: e.target.value as (typeof REL_TYPES)[number] })}>
                      {REL_TYPES.map((t) => <option key={t} value={t}>{titleCase(t)}</option>)}
                    </Select>
                    <ErrorNote error={addRel.error} />
                    <Button type="submit" size="sm" icon={<Plus className="size-3.5" />} loading={addRel.isPending}>Add</Button>
                  </form>
                )}
              </CardBody>
            </Card>
          </div>
        )}

        {tab === "sources" && <SourcesTable competitorId={id} />}
      </div>

      <Modal open={editing} onClose={() => setEditing(false)} title={`Edit ${c.name}`}>
        <CompetitorForm initial={c} onSubmit={(b) => update.mutate(b)} busy={update.isPending} error={update.error} submitLabel="Save" />
      </Modal>
    </>
  );
}
