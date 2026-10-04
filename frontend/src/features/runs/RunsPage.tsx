import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, RotateCcw } from "lucide-react";
import { useState } from "react";
import { api, call, type AgentRunOut } from "@/api/client";
import { Badge, StatusDot } from "@/components/ui/badges";
import { Button, Card, EmptyState, Modal, PageHeader, PageLoader, Select } from "@/components/ui/primitives";
import { useAuth } from "@/lib/auth";
import { dateTime, duration, timeAgo, titleCase } from "@/lib/format";
import { AgentTimeline } from "./AgentTimeline";

function RunDetail({ run, onClose }: { run: AgentRunOut; onClose: () => void }) {
  const d = useQuery({
    queryKey: ["runs", run.id],
    queryFn: () => call(api.GET("/api/v1/agent-runs/{run_id}", { params: { path: { run_id: run.id } } })),
  });
  return (
    <Modal open onClose={onClose} title={`${titleCase(run.graph)} · ${run.source_name ?? ""}`} wide>
      <div className="mb-4 flex flex-wrap gap-2 text-xs text-muted">
        <Badge>{run.status}</Badge>
        {run.outcome && <Badge>{run.outcome}</Badge>}
        <span>started {dateTime(run.started_at)}</span>
        <span>· attempt {run.attempts}</span>
      </div>
      {run.error && <pre className="mb-4 whitespace-pre-wrap rounded-lg bg-red-50 p-3 text-xs text-red-700 dark:bg-red-950/40 dark:text-red-300">{run.error}</pre>}
      {d.data ? <AgentTimeline steps={d.data.steps} /> : <PageLoader />}
    </Modal>
  );
}

export function RunsPage() {
  const { hasRole } = useAuth();
  const qc = useQueryClient();
  const [status, setStatus] = useState("");
  const [graph, setGraph] = useState("");
  const [selected, setSelected] = useState<AgentRunOut | null>(null);
  const runs = useQuery({
    queryKey: ["runs", status, graph],
    queryFn: () =>
      call(api.GET("/api/v1/agent-runs", { params: { query: { status: status || undefined, graph: graph || undefined, limit: 100 } } })),
    refetchInterval: 15_000,
    placeholderData: keepPreviousData,
  });
  const retry = useMutation({
    mutationFn: (id: string) => call(api.POST("/api/v1/agent-runs/{run_id}/retry", { params: { path: { run_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });

  return (
    <>
      <PageHeader
        title="Agent runs"
        subtitle="Audit trail of every autonomous pipeline execution"
        actions={
          <>
            <Select className="w-auto" value={graph} onChange={(e) => setGraph(e.target.value)} aria-label="Graph">
              <option value="">All pipelines</option>
              <option value="intel_pipeline">Intelligence pipeline</option>
              <option value="daily_brief">Daily brief</option>
            </Select>
            <Select className="w-auto" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
              <option value="">Active & finished (no skips)</option>
              {["running", "succeeded", "skipped", "failed", "dead_letter"].map((s) => (
                <option key={s} value={s}>
                  {titleCase(s)}
                </option>
              ))}
            </Select>
          </>
        }
      />
      <Card>
        {runs.isLoading ? (
          <PageLoader />
        ) : runs.data?.items.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-subtle">
                  <th className="px-5 py-2 font-medium">Run</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Outcome</th>
                  <th className="px-3 py-2 font-medium">Trigger</th>
                  <th className="px-3 py-2 font-medium">Started</th>
                  <th className="px-3 py-2 font-medium">Duration</th>
                  <th className="px-5 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-default">
                {runs.data.items.map((r) => (
                  <tr key={r.id} className="cursor-pointer hover:bg-surface-sunken/60" onClick={() => setSelected(r)}>
                    <td className="px-5 py-2.5">
                      <p className="font-medium">{r.source_name ?? titleCase(r.graph)}</p>
                      <p className="text-xs text-subtle">{titleCase(r.graph)}</p>
                    </td>
                    <td className="px-3 py-2.5">
                      <span className="inline-flex items-center gap-1.5">
                        <StatusDot status={r.status} /> {titleCase(r.status)}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-muted">{r.outcome ? titleCase(r.outcome) : "—"}</td>
                    <td className="px-3 py-2.5 text-muted">{r.trigger}</td>
                    <td className="px-3 py-2.5 text-muted">{timeAgo(r.started_at)}</td>
                    <td className="px-3 py-2.5 tabular-nums text-muted">
                      {r.finished_at ? duration(new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) : "…"}
                    </td>
                    <td className="px-5 py-2.5 text-right">
                      {hasRole() && ["failed", "dead_letter"].includes(r.status) && r.graph === "intel_pipeline" && (
                        <Button
                          size="sm"
                          icon={<RotateCcw className="size-3.5" />}
                          onClick={(e) => {
                            e.stopPropagation();
                            retry.mutate(r.id);
                          }}
                        >
                          Resume
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState icon={<Activity className="size-8" />} title="No runs yet" />
        )}
      </Card>
      {selected && <RunDetail run={selected} onClose={() => setSelected(null)} />}
    </>
  );
}
