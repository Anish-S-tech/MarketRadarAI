import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, ExternalLink, Minus, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, call, type EventDetail } from "@/api/client";
import {
  Badge,
  CategoryBadge,
  ConfidenceBadge,
  PriorityBadge,
  SimulatedBadge,
  StanceChip,
  ThreatTier,
} from "@/components/ui/badges";
import { Button, Card, CardBody, CardHeader, ErrorNote, PageLoader, Tabs } from "@/components/ui/primitives";
import { cn, dateTime, pct, timeAgo, titleCase } from "@/lib/format";
import { AgentTimeline } from "@/features/runs/AgentTimeline";

const ROLE_TABS = ["executive", "product", "sales", "marketing", "pricing"] as const;

function SeverityBar({ label, severity, rationale }: { label: string; severity: number; rationale: string }) {
  const color = severity >= 4 ? "bg-red-500" : severity === 3 ? "bg-orange-400" : "bg-sky-400";
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{label}</span>
        <span className="tabular-nums text-muted">{severity}/5</span>
      </div>
      <div className="mt-1 flex gap-1" aria-label={`${label} severity ${severity} of 5`}>
        {[1, 2, 3, 4, 5].map((i) => (
          <span key={i} className={cn("h-1.5 flex-1 rounded-full", i <= severity ? color : "bg-surface-sunken")} />
        ))}
      </div>
      {rationale && <p className="mt-1 text-xs text-muted">{rationale}</p>}
    </div>
  );
}

function ImpactCard({ d }: { d: EventDetail }) {
  const [role, setRole] = useState<(typeof ROLE_TABS)[number]>("executive");
  const impact = d.impact;
  if (!impact) return null;
  const dims = impact.dimensions as Record<string, { severity: number; rationale: string }>;
  return (
    <Card>
      <CardHeader title="Impact on us" subtitle={impact.summary} />
      <CardBody className="grid gap-5 md:grid-cols-2">
        <div className="space-y-4">
          {(["products", "customers", "pricing", "competitive_position"] as const).map(
            (k) => dims[k] && <SeverityBar key={k} label={titleCase(k)} severity={dims[k].severity} rationale={dims[k].rationale} />,
          )}
          {(impact.affected_products.length > 0 || impact.affected_segments.length > 0) && (
            <div className="flex flex-wrap gap-1.5 pt-1">
              {impact.affected_products.map((p) => (
                <Badge key={p} className="bg-brand-50 text-brand-800 ring-brand-600/20 dark:bg-brand-500/10 dark:text-brand-200">
                  {p}
                </Badge>
              ))}
              {impact.affected_segments.map((s) => (
                <Badge key={s}>{s}</Badge>
              ))}
            </div>
          )}
        </div>
        <div>
          <Tabs tabs={ROLE_TABS.map((r) => ({ id: r, label: titleCase(r) }))} value={role} onChange={setRole} />
          <p className="mt-3 text-sm">{impact.role_implications[role] || "No specific implication for this role."}</p>
          <h4 className="mt-5 text-xs font-semibold uppercase tracking-wide text-subtle">Recommended actions</h4>
          <ul className="mt-2 space-y-2">
            {(impact.recommended_actions as { action: string; owner_role: string; urgency: string }[]).map((a, i) => (
              <li key={i} className={cn("flex gap-2 text-sm", a.owner_role === role ? "" : "opacity-60")}>
                <Check className="mt-0.5 size-4 shrink-0 text-brand-600" />
                <span>
                  {a.action}{" "}
                  <span className="text-xs text-muted">
                    · {titleCase(a.owner_role)} · {titleCase(a.urgency)}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      </CardBody>
    </Card>
  );
}

function DiffCard({ d }: { d: EventDetail }) {
  const change = d.change;
  if (!change) return null;
  const diff = change.diff as {
    added?: string[];
    removed?: string[];
    pricing_changes?: { type: string; plan: string; description: string; pct_change?: number | null }[];
    item?: { title: string; url: string; summary: string };
  };
  return (
    <Card>
      <CardHeader
        title="What changed"
        subtitle={`${titleCase(change.kind)} · significance ${pct(change.significance)}`}
        actions={
          d.source && (
            <a href={d.source.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-muted hover:text-default">
              {d.source.name} <ExternalLink className="size-3" />
            </a>
          )
        }
      />
      <CardBody className="space-y-4">
        {diff.pricing_changes && diff.pricing_changes.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <tbody className="divide-y divide-default">
                {diff.pricing_changes.map((pc, i) => (
                  <tr key={i}>
                    <td className="py-1.5 pr-3">
                      <Badge>{titleCase(pc.type)}</Badge>
                    </td>
                    <td className="py-1.5">{pc.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {diff.item && (
          <div className="rounded-lg border border-default p-3">
            <a href={diff.item.url} target="_blank" rel="noreferrer" className="text-sm font-medium hover:underline">
              {diff.item.title}
            </a>
            <p className="mt-1 text-sm text-muted">{diff.item.summary}</p>
          </div>
        )}
        {(diff.added?.length || diff.removed?.length) ? (
          <div className="overflow-hidden rounded-lg border border-default font-mono text-xs">
            {diff.removed?.slice(0, 40).map((l, i) => (
              <div key={`r${i}`} className="flex gap-2 bg-rose-50 px-3 py-0.5 text-rose-800 dark:bg-rose-500/10 dark:text-rose-200">
                <Minus className="mt-0.5 size-3 shrink-0" />
                <span className="whitespace-pre-wrap break-words">{l}</span>
              </div>
            ))}
            {diff.added?.slice(0, 40).map((l, i) => (
              <div key={`a${i}`} className="flex gap-2 bg-emerald-50 px-3 py-0.5 text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-200">
                <Plus className="mt-0.5 size-3 shrink-0" />
                <span className="whitespace-pre-wrap break-words">{l}</span>
              </div>
            ))}
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

function EvidenceCard({ d }: { d: EventDetail }) {
  const claims = (d.verification?.claims ?? []) as {
    claim: string;
    score: number;
    supporting: number;
    contradicting: number;
    independent_domains: number;
  }[];
  const [showIrrelevant, setShowIrrelevant] = useState(false);
  const relevant = d.evidence.filter((e) => e.stances.some((s) => (s as { stance: string }).stance !== "irrelevant"));
  const shown = showIrrelevant ? d.evidence : relevant;
  return (
    <Card>
      <CardHeader
        title="Verification & evidence"
        subtitle={d.verification?.rationale}
        actions={<ConfidenceBadge level={d.verification?.level} score={d.verification?.confidence_score} />}
      />
      <CardBody className="space-y-5">
        {claims.length > 0 && (
          <div className="space-y-2">
            {claims.map((c, i) => (
              <div key={i} className="flex items-start gap-3 rounded-lg bg-surface-sunken/60 px-3 py-2">
                <span className="mt-0.5 w-10 shrink-0 text-right text-xs font-semibold tabular-nums">{pct(c.score)}</span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm">{c.claim}</p>
                  <p className="text-xs text-muted">
                    {c.supporting} supporting · {c.contradicting} contradicting · {c.independent_domains} independent domain(s)
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
        <ul className="divide-y divide-default">
          {shown.map((e) => (
            <li key={e.id} className="py-3">
              <div className="flex flex-wrap items-center gap-1.5">
                <a href={e.url} target="_blank" rel="noreferrer" className="text-sm font-medium hover:underline">
                  {e.title || e.domain}
                </a>
                <span className="text-xs text-subtle">{e.domain}</span>
                <Badge title="Source reliability tier (1 = most reliable)">tier {e.reliability_tier}</Badge>
                {e.is_primary && <Badge className="bg-brand-50 text-brand-800 ring-brand-600/20 dark:bg-brand-500/10 dark:text-brand-200">primary</Badge>}
                <Badge>{e.origin}</Badge>
              </div>
              {e.snippet && <p className="mt-1 line-clamp-3 text-xs text-muted">{e.snippet}</p>}
              <div className="mt-1.5 flex flex-wrap gap-1">
                {(e.stances as { claim_index: number; stance: string; rationale?: string }[]).map((s) => (
                  <span key={s.claim_index} title={s.rationale} className="inline-flex items-center gap-1 text-[11px] text-subtle">
                    claim {s.claim_index + 1}: <StanceChip stance={s.stance} />
                  </span>
                ))}
              </div>
            </li>
          ))}
        </ul>
        {d.evidence.length > relevant.length && (
          <button className="text-xs font-medium text-brand-700 hover:underline dark:text-brand-300" onClick={() => setShowIrrelevant((v) => !v)}>
            {showIrrelevant ? "Hide" : "Show"} {d.evidence.length - relevant.length} sources judged irrelevant
          </button>
        )}
      </CardBody>
    </Card>
  );
}

export function EventDetailPage() {
  const { id } = useParams();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["events", "detail", id], queryFn: () => call(api.GET("/api/v1/events/{event_id}", { params: { path: { event_id: id! } } })) });
  const setStatus = useMutation({
    mutationFn: (status: "acknowledged" | "actioned" | "dismissed" | "new") =>
      call(api.PATCH("/api/v1/events/{event_id}", { params: { path: { event_id: id! } }, body: { status } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["events"] }),
  });

  if (q.isLoading) return <PageLoader />;
  if (q.error || !q.data) return <ErrorNote error={q.error ?? "Not found"} />;
  const d = q.data;
  const e = d.event;
  const factors = d.priority_factors as Record<string, number>;

  return (
    <>
      <Link to="/events" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-default">
        <ArrowLeft className="size-4" /> Events
      </Link>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 max-w-3xl">
          <div className="flex flex-wrap items-center gap-1.5">
            <PriorityBadge priority={e.priority} />
            <CategoryBadge category={e.category} />
            <ConfidenceBadge level={e.confidence_level} score={e.confidence_score} />
            {e.is_simulated && <SimulatedBadge />}
            {e.stage !== "complete" && <Badge>{titleCase(e.stage)}…</Badge>}
          </div>
          <h1 className="mt-2 text-xl font-semibold tracking-tight">{e.title}</h1>
          {e.is_simulated && (
            <p className="mt-2 rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-sm text-violet-800 dark:border-violet-500/30 dark:bg-violet-500/10 dark:text-violet-200">
              Simulated demo scenario from the SimWire feed — not real news. The agents processed it exactly as they
              would a real development, so the research, verification and impact below are genuine outputs.
            </p>
          )}
          <p className="mt-1 text-sm text-muted">
            <Link to={`/competitors/${d.competitor.id}`} className="font-medium text-default hover:underline">
              {d.competitor.name}
            </Link>{" "}
            <ThreatTier tier={d.competitor.threat_tier} /> · detected {timeAgo(e.detected_at)} ({dateTime(e.detected_at)})
          </p>
        </div>
        <div className="flex gap-2">
          {(["acknowledged", "actioned", "dismissed"] as const).map((s) => (
            <Button key={s} size="sm" variant={e.status === s ? "primary" : "secondary"} onClick={() => setStatus.mutate(e.status === s ? "new" : s)} loading={setStatus.isPending && setStatus.variables === s}>
              {titleCase(s)}
            </Button>
          ))}
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Card>
            <CardBody>
              <p className="text-sm leading-relaxed">{e.summary}</p>
              {e.key_facts.length > 0 && (
                <ul className="mt-3 space-y-1">
                  {e.key_facts.map((f, i) => (
                    <li key={i} className="flex gap-2 text-sm">
                      <span className="mt-2 size-1 shrink-0 rounded-full bg-brand-500" />
                      {f}
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
          <ImpactCard d={d} />
          <EvidenceCard d={d} />
          <DiffCard d={d} />
        </div>
        <div className="space-y-5">
          {e.priority && (
            <Card>
              <CardHeader title="Why this priority" subtitle={`Score ${e.priority_score?.toFixed(2)}`} />
              <CardBody className="space-y-2">
                {Object.entries(factors)
                  .filter(([k]) => k !== "similar_recent_events")
                  .map(([k, v]) => (
                    <div key={k}>
                      <div className="flex justify-between text-xs">
                        <span className="text-muted">{titleCase(k)}</span>
                        <span className="tabular-nums">{(v as number).toFixed(2)}</span>
                      </div>
                      <div className="mt-0.5 h-1 rounded-full bg-surface-sunken">
                        <div className="h-1 rounded-full bg-brand-500" style={{ width: `${(v as number) * 100}%` }} />
                      </div>
                    </div>
                  ))}
                {d.impact?.priority_rationale && <p className="pt-2 text-xs text-subtle">{d.impact.priority_rationale}</p>}
              </CardBody>
            </Card>
          )}
          <Card>
            <CardHeader title="Agent trace" subtitle="How the agents reached this conclusion" />
            <CardBody>
              <AgentTimeline steps={d.steps} />
            </CardBody>
          </Card>
        </div>
      </div>
    </>
  );
}
