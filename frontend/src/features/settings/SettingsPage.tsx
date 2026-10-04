import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Copy, Plus, Trash2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, call, type ChangeCategory, type Priority, type Role, type SubscriptionIn, type SubscriptionOut } from "@/api/client";
import { Badge } from "@/components/ui/badges";
import { Button, Card, CardBody, CardHeader, ErrorNote, Field, Input, Modal, PageHeader, PageLoader, Select, Tabs, Textarea } from "@/components/ui/primitives";
import { useAuth } from "@/lib/auth";
import { CATEGORIES, PRIORITIES, ROLES, money, timeAgo, titleCase } from "@/lib/format";

type Tab = "company" | "subscriptions" | "users" | "keys" | "org" | "system";

const csv = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

function CompanyTab() {
  const qc = useQueryClient();
  const { hasRole } = useAuth();
  const canEdit = hasRole("executive", "product", "pricing", "marketing");
  const profile = useQuery({ queryKey: ["company"], queryFn: () => call(api.GET("/api/v1/company")) });
  const products = useQuery({ queryKey: ["company", "products"], queryFn: () => call(api.GET("/api/v1/company/products")) });
  const prices = useQuery({ queryKey: ["company", "prices"], queryFn: () => call(api.GET("/api/v1/company/prices")) });
  const segments = useQuery({ queryKey: ["company", "segments"], queryFn: () => call(api.GET("/api/v1/company/segments")) });
  const [f, setF] = useState({ name: "", website: "", description: "", positioning: "", differentiators: "", target_markets: "" });

  useEffect(() => {
    if (profile.data)
      setF({
        name: profile.data.name,
        website: profile.data.website ?? "",
        description: profile.data.description,
        positioning: profile.data.positioning,
        differentiators: profile.data.differentiators.join(", "),
        target_markets: profile.data.target_markets.join(", "),
      });
  }, [profile.data]);

  const save = useMutation({
    mutationFn: () =>
      call(
        api.PUT("/api/v1/company", {
          body: { ...f, website: f.website || null, differentiators: csv(f.differentiators), target_markets: csv(f.target_markets) },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["company"] }),
  });

  const [prod, setProd] = useState({ name: "", category: "", description: "", features: "" });
  const addProd = useMutation({
    mutationFn: () => call(api.POST("/api/v1/company/products", { body: { ...prod, features: csv(prod.features) } })),
    onSuccess: () => {
      setProd({ name: "", category: "", description: "", features: "" });
      qc.invalidateQueries({ queryKey: ["company", "products"] });
    },
  });
  const delProd = useMutation({
    mutationFn: (id: string) => call(api.DELETE("/api/v1/company/products/{item_id}", { params: { path: { item_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["company", "products"] }),
  });
  const [price, setPrice] = useState({ plan: "", price: "", period: "month" });
  const addPrice = useMutation({
    mutationFn: () => call(api.POST("/api/v1/company/prices", { body: { plan: price.plan, price: price.price || null, period: price.period, currency: "USD" } })),
    onSuccess: () => {
      setPrice({ plan: "", price: "", period: "month" });
      qc.invalidateQueries({ queryKey: ["company", "prices"] });
    },
  });
  const delPrice = useMutation({
    mutationFn: (id: string) => call(api.DELETE("/api/v1/company/prices/{item_id}", { params: { path: { item_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["company", "prices"] }),
  });
  const [seg, setSeg] = useState({ name: "", description: "", revenue_share: "" });
  const addSeg = useMutation({
    mutationFn: () => call(api.POST("/api/v1/company/segments", { body: { ...seg, revenue_share: Number(seg.revenue_share || 0) / 100 } })),
    onSuccess: () => {
      setSeg({ name: "", description: "", revenue_share: "" });
      qc.invalidateQueries({ queryKey: ["company", "segments"] });
    },
  });
  const delSeg = useMutation({
    mutationFn: (id: string) => call(api.DELETE("/api/v1/company/segments/{item_id}", { params: { path: { item_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["company", "segments"] }),
  });

  if (profile.isLoading) return <PageLoader />;
  return (
    <div className="space-y-5">
      <Card>
        <CardHeader title="Our company" subtitle="The Impact Agent evaluates every competitor move against this profile" />
        <CardBody>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Name">
                <Input required disabled={!canEdit} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
              </Field>
              <Field label="Website">
                <Input disabled={!canEdit} value={f.website} onChange={(e) => setF({ ...f, website: e.target.value })} />
              </Field>
            </div>
            <Field label="Description">
              <Textarea disabled={!canEdit} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
            </Field>
            <Field label="Positioning">
              <Textarea disabled={!canEdit} value={f.positioning} onChange={(e) => setF({ ...f, positioning: e.target.value })} />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Differentiators" hint="Comma-separated">
                <Input disabled={!canEdit} value={f.differentiators} onChange={(e) => setF({ ...f, differentiators: e.target.value })} />
              </Field>
              <Field label="Target markets" hint="Comma-separated">
                <Input disabled={!canEdit} value={f.target_markets} onChange={(e) => setF({ ...f, target_markets: e.target.value })} />
              </Field>
            </div>
            <ErrorNote error={save.error} />
            {canEdit && (
              <div className="flex justify-end">
                <Button type="submit" variant="primary" loading={save.isPending}>
                  {save.isSuccess ? "Saved" : "Save profile"}
                </Button>
              </div>
            )}
          </form>
        </CardBody>
      </Card>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card>
          <CardHeader title="Products" />
          <CardBody className="space-y-3">
            {products.data?.map((p) => (
              <div key={p.id} className="flex items-start justify-between gap-2 text-sm">
                <div>
                  <p className="font-medium">{p.name}</p>
                  <p className="text-xs text-muted">{p.category} {p.features.length > 0 && `· ${p.features.join(", ")}`}</p>
                </div>
                {canEdit && <Button size="sm" variant="ghost" onClick={() => delProd.mutate(p.id)} icon={<Trash2 className="size-3.5" />} aria-label="Delete" />}
              </div>
            ))}
            {canEdit && (
              <form className="space-y-2 border-t border-default pt-3" onSubmit={(e) => { e.preventDefault(); addProd.mutate(); }}>
                <Input placeholder="Product name" required value={prod.name} onChange={(e) => setProd({ ...prod, name: e.target.value })} />
                <Input placeholder="Category" value={prod.category} onChange={(e) => setProd({ ...prod, category: e.target.value })} />
                <Input placeholder="Features (comma-separated)" value={prod.features} onChange={(e) => setProd({ ...prod, features: e.target.value })} />
                <Button size="sm" type="submit" icon={<Plus className="size-3.5" />} loading={addProd.isPending}>Add product</Button>
              </form>
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Our pricing" />
          <CardBody className="space-y-2">
            {prices.data?.map((p) => (
              <div key={p.id} className="flex items-center justify-between text-sm">
                <span className="font-medium">{p.plan}</span>
                <span className="flex items-center gap-1 tabular-nums text-muted">
                  {money(p.price, p.currency, p.period)}
                  {canEdit && <Button size="sm" variant="ghost" onClick={() => delPrice.mutate(p.id)} icon={<Trash2 className="size-3.5" />} aria-label="Delete" />}
                </span>
              </div>
            ))}
            {canEdit && (
              <form className="flex flex-wrap gap-2 border-t border-default pt-3" onSubmit={(e) => { e.preventDefault(); addPrice.mutate(); }}>
                <Input className="flex-1" placeholder="Plan" required value={price.plan} onChange={(e) => setPrice({ ...price, plan: e.target.value })} />
                <Input className="w-24" placeholder="Price" type="number" step="0.01" value={price.price} onChange={(e) => setPrice({ ...price, price: e.target.value })} />
                <Select className="w-24" value={price.period} onChange={(e) => setPrice({ ...price, period: e.target.value })}>
                  <option value="month">/mo</option>
                  <option value="year">/yr</option>
                </Select>
                <Button size="sm" type="submit" icon={<Plus className="size-3.5" />} loading={addPrice.isPending}>Add</Button>
              </form>
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Customer segments" />
          <CardBody className="space-y-2">
            {segments.data?.map((s) => (
              <div key={s.id} className="flex items-center justify-between text-sm">
                <span>
                  <span className="font-medium">{s.name}</span> <span className="text-xs text-muted">{Math.round(s.revenue_share * 100)}% of revenue</span>
                </span>
                {canEdit && <Button size="sm" variant="ghost" onClick={() => delSeg.mutate(s.id)} icon={<Trash2 className="size-3.5" />} aria-label="Delete" />}
              </div>
            ))}
            {canEdit && (
              <form className="flex flex-wrap gap-2 border-t border-default pt-3" onSubmit={(e) => { e.preventDefault(); addSeg.mutate(); }}>
                <Input className="flex-1" placeholder="Segment" required value={seg.name} onChange={(e) => setSeg({ ...seg, name: e.target.value })} />
                <Input className="w-24" placeholder="% rev" type="number" min={0} max={100} value={seg.revenue_share} onChange={(e) => setSeg({ ...seg, revenue_share: e.target.value })} />
                <Button size="sm" type="submit" icon={<Plus className="size-3.5" />} loading={addSeg.isPending}>Add</Button>
              </form>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function SubscriptionEditor({ sub, onClose }: { sub: SubscriptionOut | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { hasRole } = useAuth();
  const isAdmin = hasRole();
  const competitors = useQuery({ queryKey: ["competitors"], queryFn: () => call(api.GET("/api/v1/competitors")) });
  const [f, setF] = useState<SubscriptionIn>({
    name: sub?.name ?? "",
    role: (sub?.role as Role | null) ?? (isAdmin ? "executive" : null),
    personal: sub ? sub.user_id !== null : !isAdmin,
    categories: (sub?.categories ?? []) as ChangeCategory[],
    competitor_ids: sub?.competitor_ids ?? [],
    min_priority: (sub?.min_priority ?? "medium") as Priority,
    channels: sub?.channels ?? ["in_app", "email"],
    include_in_brief: sub?.include_in_brief ?? true,
    is_active: sub?.is_active ?? true,
  });
  const save = useMutation({
    mutationFn: () =>
      sub
        ? call(api.PUT("/api/v1/subscriptions/{sub_id}", { params: { path: { sub_id: sub.id } }, body: f }))
        : call(api.POST("/api/v1/subscriptions", { body: f })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["subscriptions"] });
      onClose();
    },
  });
  const toggle = <T,>(arr: T[], v: T) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

  return (
    <Modal
      open
      onClose={onClose}
      title={sub ? "Edit subscription" : "New subscription"}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={() => save.mutate()} loading={save.isPending}>Save</Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Name">
          <Input value={f.name ?? ""} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="e.g. Pricing moves by primary rivals" />
        </Field>
        {isAdmin && !sub && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={!!f.personal} onChange={(e) => setF({ ...f, personal: e.target.checked })} /> Just for me (otherwise applies to everyone with a role)
          </label>
        )}
        {!f.personal && (
          <Field label="Role">
            <Select value={f.role ?? ""} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>
              {ROLES.map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}
            </Select>
          </Field>
        )}
        <Field label="Minimum priority">
          <Select value={f.min_priority} onChange={(e) => setF({ ...f, min_priority: e.target.value as Priority })}>
            {[...PRIORITIES].reverse().map((p) => <option key={p} value={p}>{titleCase(p)}</option>)}
          </Select>
        </Field>
        <div>
          <p className="mb-1 text-xs font-medium text-muted">Categories (none = all)</p>
          <div className="flex flex-wrap gap-1.5">
            {CATEGORIES.map((c) => (
              <button key={c} type="button" onClick={() => setF({ ...f, categories: toggle(f.categories ?? [], c as ChangeCategory) })}
                className={`rounded-md border px-2 py-1 text-xs ${f.categories?.includes(c as ChangeCategory) ? "border-brand-600 bg-brand-50 text-brand-800 dark:bg-brand-500/10 dark:text-brand-200" : "border-default text-muted"}`}>
                {titleCase(c)}
              </button>
            ))}
          </div>
        </div>
        <div>
          <p className="mb-1 text-xs font-medium text-muted">Competitors (none = all)</p>
          <div className="flex flex-wrap gap-1.5">
            {competitors.data?.map((c) => (
              <button key={c.id} type="button" onClick={() => setF({ ...f, competitor_ids: toggle(f.competitor_ids ?? [], c.id) })}
                className={`rounded-md border px-2 py-1 text-xs ${f.competitor_ids?.includes(c.id) ? "border-brand-600 bg-brand-50 text-brand-800 dark:bg-brand-500/10 dark:text-brand-200" : "border-default text-muted"}`}>
                {c.name}
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap gap-4 text-sm">
          {(["in_app", "email"] as const).map((ch) => (
            <label key={ch} className="flex items-center gap-2">
              <input type="checkbox" checked={f.channels?.includes(ch)} onChange={() => setF({ ...f, channels: toggle(f.channels ?? [], ch) })} />
              {ch === "in_app" ? "In-app" : "Email"}
            </label>
          ))}
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={f.include_in_brief} onChange={(e) => setF({ ...f, include_in_brief: e.target.checked })} /> Daily brief email
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} /> Active
          </label>
        </div>
        <ErrorNote error={save.error} />
      </div>
    </Modal>
  );
}

function SubscriptionsTab() {
  const qc = useQueryClient();
  const subs = useQuery({ queryKey: ["subscriptions"], queryFn: () => call(api.GET("/api/v1/subscriptions")) });
  const [editing, setEditing] = useState<SubscriptionOut | null | "new">(null);
  const remove = useMutation({
    mutationFn: (id: string) => call(api.DELETE("/api/v1/subscriptions/{sub_id}", { params: { path: { sub_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["subscriptions"] }),
  });
  return (
    <Card>
      <CardHeader
        title="Alert routing"
        subtitle="Who gets which alerts. High and critical events are emailed immediately; the rest go into the daily brief."
        actions={<Button size="sm" variant="primary" icon={<Plus className="size-3.5" />} onClick={() => setEditing("new")}>New</Button>}
      />
      <ul className="divide-y divide-default">
        {subs.data?.map((s) => (
          <li key={s.id} className="flex flex-wrap items-center gap-2 px-5 py-3 text-sm">
            <div className="min-w-0 flex-1">
              <p className="font-medium">{s.name || (s.role ? `${titleCase(s.role)} role` : "Personal")}</p>
              <p className="text-xs text-muted">
                {s.user_id ? "Personal" : `Everyone with role ${titleCase(s.role ?? "")}`} · ≥ {s.min_priority} ·{" "}
                {s.categories.length ? s.categories.join(", ") : "all categories"} · {s.channels.join(" + ")}
              </p>
            </div>
            {!s.is_active && <Badge>paused</Badge>}
            <Button size="sm" onClick={() => setEditing(s)}>Edit</Button>
            <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} onClick={() => remove.mutate(s.id)} aria-label="Delete" />
          </li>
        ))}
      </ul>
      {editing && <SubscriptionEditor sub={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </Card>
  );
}

function UsersTab() {
  const qc = useQueryClient();
  const { user: me } = useAuth();
  const users = useQuery({ queryKey: ["users"], queryFn: () => call(api.GET("/api/v1/users")) });
  const [f, setF] = useState({ email: "", full_name: "", role: "sales" as Role, password: "" });
  const create = useMutation({
    mutationFn: () => call(api.POST("/api/v1/users", { body: f })),
    onSuccess: () => {
      setF({ email: "", full_name: "", role: "sales", password: "" });
      qc.invalidateQueries({ queryKey: ["users"] });
    },
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: { role?: Role; is_active?: boolean } }) =>
      call(api.PATCH("/api/v1/users/{user_id}", { params: { path: { user_id: id } }, body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader title="Team" subtitle="Roles decide which alerts and brief edition each person receives" />
        <ul className="divide-y divide-default">
          {users.data?.map((u) => (
            <li key={u.id} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
              <div className="min-w-0 flex-1">
                <p className="font-medium">{u.full_name || u.email}</p>
                <p className="text-xs text-muted">{u.email} · last login {timeAgo(u.last_login_at)}</p>
              </div>
              <Select className="w-36" value={u.role} disabled={u.id === me?.id} onChange={(e) => update.mutate({ id: u.id, body: { role: e.target.value as Role } })}>
                {ROLES.map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}
              </Select>
              <Button size="sm" disabled={u.id === me?.id} onClick={() => update.mutate({ id: u.id, body: { is_active: !u.is_active } })}>
                {u.is_active ? "Deactivate" : "Activate"}
              </Button>
            </li>
          ))}
        </ul>
        <div className="px-5 pb-3"><ErrorNote error={update.error} /></div>
      </Card>
      <Card>
        <CardHeader title="Invite a teammate" />
        <CardBody>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
            <Field label="Email"><Input type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
            <Field label="Name"><Input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
            <Field label="Role">
              <Select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>
                {ROLES.map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}
              </Select>
            </Field>
            <Field label="Temporary password" hint="At least 10 characters"><Input type="password" minLength={10} required value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
            <ErrorNote error={create.error} />
            <Button type="submit" variant="primary" loading={create.isPending}>Create user</Button>
          </form>
        </CardBody>
      </Card>
    </div>
  );
}

function KeysTab() {
  const qc = useQueryClient();
  const keys = useQuery({ queryKey: ["api-keys"], queryFn: () => call(api.GET("/api/v1/api-keys")) });
  const [name, setName] = useState("");
  const [created, setCreated] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => call(api.POST("/api/v1/api-keys", { body: { name, role: "executive" } })),
    onSuccess: (k) => {
      setCreated(k.key);
      setName("");
      qc.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });
  const revoke = useMutation({
    mutationFn: (id: string) => call(api.DELETE("/api/v1/api-keys/{key_id}", { params: { path: { key_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }),
  });
  return (
    <Card>
      <CardHeader title="API keys" subtitle="For integrations (BI tools, Slack bots, scripts). Sent as a Bearer token." />
      <CardBody className="space-y-4">
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <Input required placeholder="Key name, e.g. Slack bot" value={name} onChange={(e) => setName(e.target.value)} />
          <Button type="submit" variant="primary" loading={create.isPending}>Create</Button>
        </form>
        {created && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/40">
            <p className="font-medium">Copy this key now — it won't be shown again.</p>
            <div className="mt-2 flex items-center gap-2">
              <code className="flex-1 break-all rounded bg-surface px-2 py-1 font-mono text-xs">{created}</code>
              <Button size="sm" icon={<Copy className="size-3.5" />} onClick={() => navigator.clipboard.writeText(created)}>Copy</Button>
            </div>
          </div>
        )}
        <ul className="divide-y divide-default">
          {keys.data?.map((k) => (
            <li key={k.id} className="flex items-center gap-3 py-2.5 text-sm">
              <div className="flex-1">
                <p className="font-medium">{k.name}</p>
                <p className="text-xs text-muted">mr_{k.prefix}_… · last used {timeAgo(k.last_used_at)}</p>
              </div>
              {k.revoked_at ? <Badge>revoked</Badge> : <Button size="sm" variant="ghost" onClick={() => revoke.mutate(k.id)}>Revoke</Button>}
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}

function OrgTab() {
  const qc = useQueryClient();
  const org = useQuery({ queryKey: ["org"], queryFn: () => call(api.GET("/api/v1/org")) });
  const [hour, setHour] = useState(7);
  const [tiers, setTiers] = useState("");
  useEffect(() => {
    if (org.data) {
      setHour(org.data.brief_hour_utc);
      const t = (org.data.settings.domain_tiers ?? {}) as Record<string, number>;
      setTiers(Object.entries(t).map(([d, v]) => `${d}=${v}`).join("\n"));
    }
  }, [org.data]);
  const save = useMutation({
    mutationFn: () => {
      const domain_tiers = Object.fromEntries(
        tiers.split("\n").map((l) => l.split("=").map((x) => x.trim())).filter(([d, v]) => d && Number(v) >= 1 && Number(v) <= 4).map(([d, v]) => [d, Number(v)]),
      );
      return call(api.PATCH("/api/v1/org", { body: { brief_hour_utc: hour, settings: { ...(org.data?.settings ?? {}), domain_tiers } } }));
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["org"] }),
  });
  if (!org.data) return <PageLoader />;
  return (
    <Card>
      <CardHeader title={org.data.name} subtitle={`Organisation ID ${org.data.id}`} />
      <CardBody className="space-y-4">
        <Field label="Daily brief time (UTC hour)">
          <Select className="w-40" value={hour} onChange={(e) => setHour(Number(e.target.value))}>
            {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00 UTC</option>)}
          </Select>
        </Field>
        <Field label="Source reliability overrides" hint="One per line: domain=tier (1 most reliable … 4 least). Competitor-owned domains are always tier 1.">
          <Textarea className="font-mono text-xs" rows={5} value={tiers} onChange={(e) => setTiers(e.target.value)} placeholder={"industry-analyst.com=2\nrumour-blog.net=4"} />
        </Field>
        <ErrorNote error={save.error} />
        <Button variant="primary" onClick={() => save.mutate()} loading={save.isPending}>Save</Button>
      </CardBody>
    </Card>
  );
}

function SystemTab() {
  const llm = useQuery({ queryKey: ["system", "llm"], queryFn: () => call(api.GET("/api/v1/system/llm")) });
  if (!llm.data) return <PageLoader />;
  const l = llm.data;
  const Row = ({ k, v }: { k: string; v: React.ReactNode }) => (
    <div className="flex justify-between gap-4 py-2 text-sm"><span className="text-muted">{k}</span><span className="text-right font-medium">{v}</span></div>
  );
  return (
    <Card>
      <CardHeader title="Language models" subtitle="Local models served by Ollama; the agents fall back to deterministic heuristics if they are unreachable" />
      <CardBody className="divide-y divide-default">
        <Row k="Provider" v={l.provider} />
        <Row k="Host" v={<code className="font-mono text-xs">{l.host}</code>} />
        <Row k="Status" v={l.reachable ? <span className="inline-flex items-center gap-1 text-emerald-600"><CheckCircle2 className="size-4" /> reachable</span> : <span className="inline-flex items-center gap-1 text-red-600"><XCircle className="size-4" /> unreachable</span>} />
        <Row k="Classification model" v={l.classify_model} />
        <Row k="Reasoning model" v={l.reason_model} />
        <Row k="Embedding model" v={l.embed_model} />
        <Row k="Installed" v={l.available_models.join(", ") || "—"} />
        {l.missing_models.length > 0 && <Row k="Missing" v={<span className="text-amber-600">ollama pull {l.missing_models.join(" ")}</span>} />}
      </CardBody>
    </Card>
  );
}

export function SettingsPage() {
  const { hasRole } = useAuth();
  const isAdmin = hasRole();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "company";
  const tabs: { id: Tab; label: string }[] = [
    { id: "company", label: "Company" },
    { id: "subscriptions", label: "Alert routing" },
    ...(isAdmin
      ? ([
          { id: "users", label: "Users" },
          { id: "keys", label: "API keys" },
          { id: "org", label: "Organisation" },
        ] as { id: Tab; label: string }[])
      : []),
    { id: "system", label: "System" },
  ];
  return (
    <>
      <PageHeader title="Settings" />
      <Tabs tabs={tabs} value={tab} onChange={(t) => setParams({ tab: t })} />
      <div className="mt-5">
        {tab === "company" && <CompanyTab />}
        {tab === "subscriptions" && <SubscriptionsTab />}
        {tab === "users" && isAdmin && <UsersTab />}
        {tab === "keys" && isAdmin && <KeysTab />}
        {tab === "org" && isAdmin && <OrgTab />}
        {tab === "system" && <SystemTab />}
      </div>
    </>
  );
}
