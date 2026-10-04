import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, call, type CompetitorIn } from "@/api/client";
import { PriorityBadge, ThreatTier } from "@/components/ui/badges";
import { Button, Card, EmptyState, ErrorNote, Field, Input, Modal, PageHeader, PageLoader, Select, Textarea } from "@/components/ui/primitives";
import { useAuth } from "@/lib/auth";
import { cn, timeAgo } from "@/lib/format";

const THREAT_LABEL: Record<number, string> = {
  5: "Primary rival",
  4: "Major threat",
  3: "Competitor",
  2: "Minor",
  1: "Peripheral",
};

const MONO_COLORS = [
  "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
  "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300",
  "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
  "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
  "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300",
  "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
];

export function Monogram({ name, size = "md" }: { name: string; size?: "md" | "lg" }) {
  const hash = [...name].reduce((h, ch) => (h * 31 + ch.charCodeAt(0)) >>> 0, 7);
  const initials = name.split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-xl font-semibold",
        size === "lg" ? "size-12 text-base" : "size-10 text-sm",
        MONO_COLORS[hash % MONO_COLORS.length],
      )}
      aria-hidden="true"
    >
      {initials}
    </span>
  );
}

export function CompetitorForm({
  initial,
  onSubmit,
  busy,
  error,
  submitLabel,
}: {
  initial?: Partial<CompetitorIn>;
  onSubmit: (c: CompetitorIn) => void;
  busy: boolean;
  error: unknown;
  submitLabel: string;
}) {
  const [f, setF] = useState({
    name: initial?.name ?? "",
    domain: initial?.domain ?? "",
    description: initial?.description ?? "",
    threat_tier: initial?.threat_tier ?? 3,
    segments: (initial?.segments ?? []).join(", "),
    ticker: initial?.ticker ?? "",
    cik: initial?.cik ?? "",
  });
  return (
    <form
      id="competitor-form"
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({
          name: f.name,
          domain: f.domain,
          description: f.description,
          threat_tier: Number(f.threat_tier),
          segments: f.segments.split(",").map((s) => s.trim()).filter(Boolean),
          aliases: initial?.aliases ?? [],
          ticker: f.ticker || null,
          cik: f.cik || null,
          is_active: initial?.is_active ?? true,
        });
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name">
          <Input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </Field>
        <Field label="Primary domain" hint="Used to recognise first-party (primary) sources">
          <Input required placeholder="acme.com" value={f.domain} onChange={(e) => setF({ ...f, domain: e.target.value })} />
        </Field>
      </div>
      <Field label="Description">
        <Textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
      </Field>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Threat tier">
          <Select value={f.threat_tier} onChange={(e) => setF({ ...f, threat_tier: Number(e.target.value) })}>
            {[5, 4, 3, 2, 1].map((t) => (
              <option key={t} value={t}>
                {t} {t === 5 ? "— primary rival" : t === 1 ? "— peripheral" : ""}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Ticker">
          <Input value={f.ticker} onChange={(e) => setF({ ...f, ticker: e.target.value })} />
        </Field>
        <Field label="SEC CIK" hint="Enables earnings/filing monitoring">
          <Input value={f.cik} onChange={(e) => setF({ ...f, cik: e.target.value })} />
        </Field>
      </div>
      <Field label="Segments" hint="Comma-separated">
        <Input value={f.segments} onChange={(e) => setF({ ...f, segments: e.target.value })} />
      </Field>
      <ErrorNote error={error} />
      <div className="flex justify-end">
        <Button type="submit" variant="primary" loading={busy}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}

export function CompetitorsPage() {
  const { hasRole } = useAuth();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const list = useQuery({ queryKey: ["competitors"], queryFn: () => call(api.GET("/api/v1/competitors")) });
  const create = useMutation({
    mutationFn: (body: CompetitorIn) => call(api.POST("/api/v1/competitors", { body })),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["competitors"] });
      setOpen(false);
      navigate(`/competitors/${c.id}?tab=sources`);
    },
  });

  return (
    <>
      <PageHeader
        title="Competitors"
        subtitle="Profiles maintained continuously by the agents"
        actions={
          hasRole("executive", "product", "marketing", "pricing") && (
            <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>
              Add competitor
            </Button>
          )
        }
      />
      {list.isLoading ? (
        <PageLoader />
      ) : list.data?.length ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {list.data.map((c) => (
            <Link key={c.id} to={`/competitors/${c.id}`}>
              <Card className="flex h-full flex-col p-5 transition-all hover:-translate-y-0.5 hover:border-brand-300 hover:shadow-md dark:hover:border-brand-700">
                <div className="flex items-start gap-3">
                  <Monogram name={c.name} />
                  <div className="min-w-0 flex-1">
                    <h3 className="truncate font-semibold">{c.name}</h3>
                    <p className="truncate text-xs text-subtle">{c.domain}</p>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <ThreatTier tier={c.threat_tier} />
                    <span className="text-[11px] text-subtle">{THREAT_LABEL[c.threat_tier]}</span>
                  </div>
                </div>
                <p className="mt-3 line-clamp-3 flex-1 text-sm leading-relaxed text-muted">
                  {c.summary || c.description || "No profile yet."}
                </p>
                <div className="mt-4 grid grid-cols-3 gap-2 border-t border-default pt-3">
                  <div>
                    <p className="text-base font-semibold tabular-nums">{c.events_30d}</p>
                    <p className="text-[11px] text-subtle">events · 30d</p>
                  </div>
                  <div>
                    <p className="text-base font-semibold tabular-nums">{c.source_count}</p>
                    <p className="text-[11px] text-subtle">sources</p>
                  </div>
                  <div className="flex flex-col items-end justify-center">
                    {c.top_priority_30d ? <PriorityBadge priority={c.top_priority_30d} /> : <span className="text-xs text-subtle">{timeAgo(c.last_event_at)}</span>}
                  </div>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      ) : (
        <Card>
          <EmptyState icon={<Building2 className="size-8" />} title="No competitors yet">
            Add a competitor, then attach sources (pricing page, blog RSS, news, filings) for the agents to monitor.
          </EmptyState>
        </Card>
      )}
      <Modal open={open} onClose={() => setOpen(false)} title="Add competitor">
        <CompetitorForm onSubmit={(c) => create.mutate(c)} busy={create.isPending} error={create.error} submitLabel="Create" />
      </Modal>
    </>
  );
}
