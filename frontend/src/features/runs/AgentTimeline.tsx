import { useState } from "react";
import type { AgentStepOut } from "@/api/client";
import { StatusDot } from "@/components/ui/badges";
import { cn, duration, titleCase } from "@/lib/format";

const AGENT_LABELS: Record<string, string> = {
  scout: "Scout Agent",
  change_detection: "Change Detection Agent",
  research: "Research Agent",
  verification: "Verification Agent",
  knowledge: "Knowledge update",
  impact: "Impact Analysis Agent",
  prioritize: "Prioritization",
  alert: "Alert Agent",
  brief_gather: "Brief: gather",
  brief_summarize: "Brief: summarise",
  brief_compose: "Brief: compose",
  brief_deliver: "Brief: deliver",
};

export function AgentTimeline({ steps }: { steps: AgentStepOut[] }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!steps.length) return <p className="text-sm text-muted">No trace recorded.</p>;
  return (
    <ol className="relative space-y-3 border-l border-default pl-4">
      {steps.map((s) => {
        const models = (s.models as { model: string; task: string }[]).map((m) => `${m.task}: ${m.model}`);
        return (
          <li key={s.id} className="relative">
            <span className="absolute -left-[21px] top-1.5">
              <StatusDot status={s.status} />
            </span>
            <button className="w-full text-left" onClick={() => setOpen(open === s.id ? null : s.id)}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-sm font-medium">{AGENT_LABELS[s.agent] ?? titleCase(s.agent)}</span>
                <span className="shrink-0 text-xs tabular-nums text-subtle">{duration(s.latency_ms)}</span>
              </div>
              {models.length > 0 && <p className="truncate text-xs text-subtle">{models.join(" · ")}</p>}
              {s.error && <p className="mt-0.5 text-xs text-red-600">{s.error}</p>}
            </button>
            {open === s.id && (
              <pre className={cn("mt-2 max-h-72 overflow-auto rounded-lg bg-surface-sunken p-2.5 font-mono text-[11px] leading-relaxed text-muted")}>
                {JSON.stringify(s.output_summary, null, 2)}
              </pre>
            )}
          </li>
        );
      })}
    </ol>
  );
}
