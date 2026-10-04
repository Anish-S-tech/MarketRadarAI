import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Newspaper, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, call } from "@/api/client";
import { Markdown } from "@/components/ui/Markdown";
import { Button, Card, CardBody, EmptyState, ErrorNote, PageHeader, PageLoader, Select } from "@/components/ui/primitives";
import { useAuth } from "@/lib/auth";
import { cn, timeAgo, titleCase } from "@/lib/format";

const EDITIONS = ["general", "executive", "product", "sales", "marketing", "pricing"];

export function BriefsPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { user, hasRole } = useAuth();
  const [role, setRole] = useState(user && user.role !== "admin" ? user.role : "general");
  const list = useQuery({
    queryKey: ["briefs", "list", role],
    queryFn: () => call(api.GET("/api/v1/briefs", { params: { query: { role, limit: 60 } } })),
  });
  const selectedId = id ?? list.data?.[0]?.id;
  const brief = useQuery({
    queryKey: ["briefs", "detail", selectedId],
    queryFn: () => call(api.GET("/api/v1/briefs/{brief_id}", { params: { path: { brief_id: selectedId! } } })),
    enabled: !!selectedId,
  });
  const generate = useMutation({
    mutationFn: () => call(api.POST("/api/v1/briefs/generate", { body: { sync: true, deliver: false, window_hours: 24 } })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["briefs"] });
      navigate("/briefs");
    },
  });

  const byDate = useMemo(() => list.data ?? [], [list.data]);

  return (
    <>
      <PageHeader
        title="Daily briefs"
        subtitle="Generated every morning from the last 24 hours of intelligence"
        actions={
          <>
            <Select value={role} onChange={(e) => { setRole(e.target.value); navigate("/briefs"); }} className="w-auto" aria-label="Edition">
              {EDITIONS.map((r) => (
                <option key={r} value={r}>
                  {titleCase(r)} edition
                </option>
              ))}
            </Select>
            {hasRole("executive") && (
              <Button variant="primary" icon={<Sparkles className="size-4" />} onClick={() => generate.mutate()} loading={generate.isPending}>
                Generate now
              </Button>
            )}
          </>
        }
      />
      <ErrorNote error={generate.error} />
      <div className="grid gap-5 lg:grid-cols-4">
        <Card className="h-fit lg:col-span-1">
          {list.isLoading ? (
            <PageLoader />
          ) : byDate.length ? (
            <ul className="divide-y divide-default">
              {byDate.map((b) => (
                <li key={b.id}>
                  <button
                    onClick={() => navigate(`/briefs/${b.id}`)}
                    className={cn("w-full px-4 py-2.5 text-left hover:bg-surface-sunken/60", selectedId === b.id && "bg-brand-50 dark:bg-brand-500/10")}
                  >
                    <p className="text-sm font-medium">{new Date(b.brief_date + "T00:00:00").toLocaleDateString(undefined, { dateStyle: "medium" })}</p>
                    <p className="line-clamp-2 text-xs text-muted">{b.title}</p>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState icon={<Newspaper className="size-7" />} title="No briefs yet" />
          )}
        </Card>
        <Card className="lg:col-span-3">
          <CardBody>
            {brief.isLoading ? (
              <PageLoader />
            ) : brief.data ? (
              <>
                <p className="mb-3 text-xs text-subtle">
                  {titleCase(brief.data.role)} edition · generated {timeAgo(brief.data.generated_at)}
                  {brief.data.emailed_at && ` · emailed ${timeAgo(brief.data.emailed_at)}`}
                </p>
                <Markdown>{brief.data.content_md}</Markdown>
              </>
            ) : (
              <p className="text-sm text-muted">Select a brief.</p>
            )}
          </CardBody>
        </Card>
      </div>
    </>
  );
}
