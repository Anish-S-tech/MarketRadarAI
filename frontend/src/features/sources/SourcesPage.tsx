import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, History, Pause, Play, Plus, RefreshCw, Rss, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, call, type SourceIn, type SourceOut, type SourceTestOut, type SourceType } from "@/api/client";
import { Badge, StatusDot } from "@/components/ui/badges";
import { Button, Card, EmptyState, ErrorNote, Field, Input, Modal, PageHeader, PageLoader, Select } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/lib/auth";
import { SOURCE_TYPES, dateTime, timeAgo, titleCase } from "@/lib/format";

const TYPE_HELP: Record<string, string> = {
  pricing: "A pricing page. Plans and prices are extracted and diffed structurally.",
  webpage: "Any page (product, homepage, positioning). Text changes are diffed.",
  changelog: "A changelog or release-notes page.",
  blog_rss: "An RSS/Atom feed. Every new post is analysed.",
  news: "News coverage via the GDELT news API. Leave the URL blank to build it from the query below.",
  sec_filing: "SEC EDGAR filings (10-K, 10-Q, 8-K). Needs the company CIK.",
  sitemap: "sitemap.xml — new URLs often reveal unannounced products.",
};

function SourceForm({ competitorId, onDone }: { competitorId?: string; onDone: () => void }) {
  const qc = useQueryClient();
  const competitors = useQuery({ queryKey: ["competitors"], queryFn: () => call(api.GET("/api/v1/competitors")) });
  const [f, setF] = useState({
    competitor_id: competitorId ?? "",
    name: "",
    source_type: "pricing" as SourceType,
    url: "",
    check_interval_minutes: 360,
    render_js: false,
    include_selectors: "",
    ignore_selectors: "",
    query: "",
    cik: "",
  });
  const [test, setTest] = useState<SourceTestOut | null>(null);

  const body = (): SourceIn => ({
    competitor_id: f.competitor_id,
    name: f.name || titleCase(f.source_type),
    source_type: f.source_type,
    url: f.url,
    check_interval_minutes: Number(f.check_interval_minutes),
    render_js: f.render_js,
    include_selectors: f.include_selectors.split(",").map((s) => s.trim()).filter(Boolean),
    ignore_selectors: f.ignore_selectors.split(",").map((s) => s.trim()).filter(Boolean),
    config: {
      ...(f.query ? { query: f.query } : {}),
      ...(f.cik ? { cik: f.cik } : {}),
    },
    is_active: true,
  });

  const create = useMutation({
    mutationFn: () => call(api.POST("/api/v1/sources", { body: body() })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sources"] });
      onDone();
    },
  });
  const runTest = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/v1/sources/test", {
          body: { source_type: f.source_type, url: f.url, render_js: f.render_js, include_selectors: body().include_selectors, ignore_selectors: body().ignore_selectors, config: body().config },
        }),
      ),
    onSuccess: setTest,
  });

  const needsUrl = !["news", "sec_filing"].includes(f.source_type);
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {!competitorId && (
          <Field label="Competitor">
            <Select required value={f.competitor_id} onChange={(e) => setF({ ...f, competitor_id: e.target.value })}>
              <option value="">Select…</option>
              {competitors.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <Field label="Type" hint={TYPE_HELP[f.source_type]}>
          <Select value={f.source_type} onChange={(e) => setF({ ...f, source_type: e.target.value as SourceType })}>
            {SOURCE_TYPES.map((t) => (
              <option key={t} value={t}>
                {titleCase(t)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Name">
          <Input placeholder={titleCase(f.source_type)} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </Field>
      </div>
      <Field label={needsUrl ? "URL" : "URL (optional)"}>
        <Input type="url" required={needsUrl} placeholder="https://" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} />
      </Field>
      {f.source_type === "news" && (
        <Field label="News query" hint='e.g. "Acme Insights" OR acmeinsights.com'>
          <Input value={f.query} onChange={(e) => setF({ ...f, query: e.target.value })} />
        </Field>
      )}
      {f.source_type === "sec_filing" && (
        <Field label="CIK" hint="Falls back to the competitor's CIK">
          <Input value={f.cik} onChange={(e) => setF({ ...f, cik: e.target.value })} />
        </Field>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Check every">
          <Select value={f.check_interval_minutes} onChange={(e) => setF({ ...f, check_interval_minutes: Number(e.target.value) })}>
            {[
              [15, "15 minutes"],
              [60, "hour"],
              [360, "6 hours"],
              [720, "12 hours"],
              [1440, "day"],
              [10080, "week"],
            ].map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </Select>
        </Field>
        {needsUrl && (
          <label className="mt-6 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={f.render_js} onChange={(e) => setF({ ...f, render_js: e.target.checked })} />
            Render JavaScript (headless browser)
          </label>
        )}
      </div>
      {needsUrl && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Only watch (CSS selectors)" hint="Comma-separated, e.g. .pricing-table">
            <Input value={f.include_selectors} onChange={(e) => setF({ ...f, include_selectors: e.target.value })} />
          </Field>
          <Field label="Ignore (CSS selectors)" hint="e.g. .testimonials, #cookie">
            <Input value={f.ignore_selectors} onChange={(e) => setF({ ...f, ignore_selectors: e.target.value })} />
          </Field>
        </div>
      )}
      {test && (
        <div className="rounded-lg border border-default bg-surface-sunken/60 p-3 text-xs">
          {test.ok ? (
            <>
              <p className="font-medium">
                ✓ Fetched via {test.fetch_method} · {test.chars.toLocaleString()} characters{test.items.length ? ` · ${test.items.length} items` : ""}
              </p>
              <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap font-mono text-muted">
                {test.items.length ? test.items.map((i) => `• ${(i as { title: string }).title}`).join("\n") : test.text_preview}
              </pre>
            </>
          ) : (
            <p className="text-red-600">✗ {test.error}</p>
          )}
        </div>
      )}
      <ErrorNote error={create.error ?? runTest.error} />
      <div className="flex justify-end gap-2">
        <Button type="button" icon={<FlaskConical className="size-4" />} onClick={() => runTest.mutate()} loading={runTest.isPending} disabled={needsUrl && !f.url}>
          Test fetch
        </Button>
        <Button type="submit" variant="primary" loading={create.isPending}>
          Add source
        </Button>
      </div>
    </form>
  );
}

function SnapshotsModal({ source, onClose }: { source: SourceOut; onClose: () => void }) {
  const snaps = useQuery({
    queryKey: ["sources", source.id, "snapshots"],
    queryFn: () => call(api.GET("/api/v1/sources/{source_id}/snapshots", { params: { path: { source_id: source.id } } })),
  });
  const [selected, setSelected] = useState<string | null>(null);
  const snap = useQuery({
    queryKey: ["snapshot", selected],
    queryFn: () => call(api.GET("/api/v1/snapshots/{snapshot_id}", { params: { path: { snapshot_id: selected! } } })),
    enabled: !!selected,
  });
  return (
    <Modal open onClose={onClose} title={`Snapshots · ${source.name}`} wide>
      <div className="grid gap-4 md:grid-cols-3">
        <ul className="max-h-[55vh] space-y-1 overflow-y-auto">
          {snaps.data?.map((s) => (
            <li key={s.id}>
              <button
                onClick={() => setSelected(s.id)}
                className={`w-full rounded-lg px-2.5 py-1.5 text-left text-xs ${selected === s.id ? "bg-brand-50 dark:bg-brand-500/10" : "hover:bg-surface-sunken"}`}
              >
                <p className="font-medium">{dateTime(s.fetched_at)}</p>
                <p className="text-subtle">
                  {s.fetch_method} · {s.content_hash.slice(0, 10)}
                </p>
              </button>
            </li>
          ))}
          {snaps.data?.length === 0 && <p className="text-sm text-muted">No snapshots yet.</p>}
        </ul>
        <div className="md:col-span-2">
          {snap.data ? (
            <>
              {snap.data.blob_key && (
                <a className="text-xs font-medium text-brand-700 hover:underline dark:text-brand-300" href={`/api/v1/snapshots/${snap.data.id}/raw`} target="_blank" rel="noreferrer">
                  View raw capture
                </a>
              )}
              <pre className="mt-2 max-h-[50vh] overflow-auto whitespace-pre-wrap rounded-lg bg-surface-sunken p-3 font-mono text-xs text-muted">{snap.data.text}</pre>
              {Object.keys(snap.data.structured).length > 0 && (
                <details className="mt-2 text-xs">
                  <summary className="cursor-pointer font-medium">Structured extraction</summary>
                  <pre className="mt-1 max-h-60 overflow-auto rounded-lg bg-surface-sunken p-3 font-mono">{JSON.stringify(snap.data.structured, null, 2)}</pre>
                </details>
              )}
            </>
          ) : (
            <p className="text-sm text-muted">Select a snapshot to inspect the captured text.</p>
          )}
        </div>
      </div>
    </Modal>
  );
}

export function SourcesTable({ competitorId }: { competitorId?: string }) {
  const { hasRole } = useAuth();
  const canEdit = hasRole("executive", "product", "marketing", "pricing");
  const qc = useQueryClient();
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const [history, setHistory] = useState<SourceOut | null>(null);
  const sources = useQuery({
    queryKey: ["sources", competitorId ?? "all"],
    queryFn: () => call(api.GET("/api/v1/sources", { params: { query: { competitor_id: competitorId } } })),
    refetchInterval: 30_000,
  });
  const competitors = useQuery({ queryKey: ["competitors"], queryFn: () => call(api.GET("/api/v1/competitors")), enabled: !competitorId });
  const names = Object.fromEntries((competitors.data ?? []).map((c) => [c.id, c.name]));

  const check = useMutation({
    mutationFn: (id: string) => call(api.POST("/api/v1/sources/{source_id}/check", { params: { path: { source_id: id } } })),
    onSuccess: () => toast({ title: "Check queued — the agents are on it" }),
  });
  const toggle = useMutation({
    mutationFn: (s: SourceOut) => call(api.PATCH("/api/v1/sources/{source_id}", { params: { path: { source_id: s.id } }, body: { is_active: !s.is_active } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  });
  const remove = useMutation({
    mutationFn: (id: string) => call(api.DELETE("/api/v1/sources/{source_id}", { params: { path: { source_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  });

  return (
    <Card>
      <div className="flex items-center justify-between border-b border-default px-5 py-3">
        <p className="text-sm font-semibold">{sources.data?.length ?? 0} sources</p>
        {canEdit && (
          <Button size="sm" variant="primary" icon={<Plus className="size-3.5" />} onClick={() => setAdding(true)}>
            Add source
          </Button>
        )}
      </div>
      {sources.isLoading ? (
        <PageLoader />
      ) : sources.data?.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-subtle">
                <th className="px-5 py-2 font-medium">Source</th>
                {!competitorId && <th className="px-3 py-2 font-medium">Competitor</th>}
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Last checked</th>
                <th className="px-3 py-2 font-medium">Next</th>
                <th className="px-5 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-default">
              {sources.data.map((s) => (
                <tr key={s.id} className={s.is_active ? "" : "opacity-50"}>
                  <td className="max-w-xs px-5 py-2.5">
                    <div className="flex items-center gap-2">
                      <Badge>{titleCase(s.source_type)}</Badge>
                      <span className="truncate font-medium">{s.name}</span>
                    </div>
                    <a href={s.url} target="_blank" rel="noreferrer" className="block truncate text-xs text-subtle hover:underline">
                      {s.url}
                    </a>
                  </td>
                  {!competitorId && (
                    <td className="px-3 py-2.5">
                      <Link to={`/competitors/${s.competitor_id}`} className="hover:underline">
                        {names[s.competitor_id] ?? "—"}
                      </Link>
                    </td>
                  )}
                  <td className="px-3 py-2.5">
                    <span className="inline-flex items-center gap-1.5" title={s.last_error ?? undefined}>
                      <StatusDot status={s.last_status} />
                      {s.last_status ? titleCase(s.last_status) : "Pending"}
                      {s.consecutive_failures > 0 && <span className="text-xs text-red-600">×{s.consecutive_failures}</span>}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-muted">{timeAgo(s.last_checked_at)}</td>
                  <td className="px-3 py-2.5 text-muted">{s.is_active ? timeAgo(s.next_check_at) : "paused"}</td>
                  <td className="px-5 py-2.5">
                    <div className="flex justify-end gap-1">
                      <Button size="sm" variant="ghost" title="Snapshot history" onClick={() => setHistory(s)} icon={<History className="size-3.5" />} />
                      {canEdit && (
                        <>
                          <Button size="sm" variant="ghost" title="Check now" onClick={() => check.mutate(s.id)} icon={<RefreshCw className="size-3.5" />} />
                          <Button size="sm" variant="ghost" title={s.is_active ? "Pause" : "Resume"} onClick={() => toggle.mutate(s)} icon={s.is_active ? <Pause className="size-3.5" /> : <Play className="size-3.5" />} />
                          <Button size="sm" variant="ghost" title="Delete" onClick={() => confirm(`Delete source ${s.name}?`) && remove.mutate(s.id)} icon={<Trash2 className="size-3.5" />} />
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState icon={<Rss className="size-8" />} title="No sources yet">
          Sources are what the Scout Agent watches: pricing pages, blogs, news, filings.
        </EmptyState>
      )}
      <Modal open={adding} onClose={() => setAdding(false)} title="Add source" wide>
        <SourceForm competitorId={competitorId} onDone={() => setAdding(false)} />
      </Modal>
      {history && <SnapshotsModal source={history} onClose={() => setHistory(null)} />}
    </Card>
  );
}

export function SourcesPage() {
  return (
    <>
      <PageHeader title="Sources" subtitle="What the Scout Agent monitors, and how it's doing" />
      <SourcesTable />
    </>
  );
}
