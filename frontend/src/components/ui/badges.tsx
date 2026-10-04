import { AlertTriangle, CheckCircle2, CircleHelp, FlaskConical, ShieldQuestion } from "lucide-react";
import type { ReactNode } from "react";
import { cn, titleCase } from "@/lib/format";

export function Badge({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset",
        className ?? "bg-surface-sunken text-muted ring-transparent",
      )}
    >
      {children}
    </span>
  );
}

const PRIORITY_STYLES: Record<string, string> = {
  critical: "bg-red-50 text-red-700 ring-red-600/20 dark:bg-red-500/10 dark:text-red-300 dark:ring-red-400/30",
  high: "bg-orange-50 text-orange-700 ring-orange-600/20 dark:bg-orange-500/10 dark:text-orange-300 dark:ring-orange-400/30",
  medium: "bg-sky-50 text-sky-700 ring-sky-600/20 dark:bg-sky-500/10 dark:text-sky-300 dark:ring-sky-400/30",
  low: "bg-slate-50 text-slate-600 ring-slate-500/20 dark:bg-slate-500/10 dark:text-slate-300 dark:ring-slate-400/30",
};

export const PRIORITY_DOT: Record<string, string> = {
  critical: "bg-red-500",
  high: "bg-orange-500",
  medium: "bg-sky-500",
  low: "bg-slate-400",
};

/** Chart colours per priority (validated to stay distinguishable in both themes). */
export const PRIORITY_CHART: Record<string, string> = {
  critical: "#dc2626",
  high: "#ea7a0c",
  medium: "#0ea5e9",
  low: "#94a3b8",
};

export function PriorityBadge({ priority }: { priority?: string | null }) {
  if (!priority) return <Badge>pending</Badge>;
  return (
    <Badge className={PRIORITY_STYLES[priority]}>
      <span className={cn("size-1.5 rounded-full", PRIORITY_DOT[priority])} />
      {titleCase(priority)}
    </Badge>
  );
}

const CONF: Record<string, { cls: string; icon: ReactNode }> = {
  confirmed: {
    cls: "bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-400/30",
    icon: <CheckCircle2 className="size-3" />,
  },
  likely: {
    cls: "bg-teal-50 text-teal-700 ring-teal-600/20 dark:bg-teal-500/10 dark:text-teal-300 dark:ring-teal-400/30",
    icon: <CheckCircle2 className="size-3" />,
  },
  unverified: {
    cls: "bg-amber-50 text-amber-700 ring-amber-600/20 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-400/30",
    icon: <CircleHelp className="size-3" />,
  },
  disputed: {
    cls: "bg-rose-50 text-rose-700 ring-rose-600/20 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-400/30",
    icon: <AlertTriangle className="size-3" />,
  },
};

export function ConfidenceBadge({ level, score }: { level?: string | null; score?: number | null }) {
  if (!level) {
    return (
      <Badge>
        <ShieldQuestion className="size-3" /> unverified
      </Badge>
    );
  }
  const c = CONF[level] ?? CONF.unverified;
  return (
    <Badge className={c.cls} title="Verification confidence">
      {c.icon}
      {titleCase(level)}
      {score !== null && score !== undefined && <span className="opacity-70">· {Math.round(score * 100)}%</span>}
    </Badge>
  );
}

/** Marks events that came from a simulated demo feed, so they are never mistaken for real news. */
export function SimulatedBadge() {
  return (
    <Badge
      title="Simulated demo scenario — not real news"
      className="bg-violet-50 text-violet-700 ring-violet-600/20 dark:bg-violet-500/10 dark:text-violet-300 dark:ring-violet-400/30"
    >
      <FlaskConical className="size-3" /> Simulated
    </Badge>
  );
}

export function CategoryBadge({ category }: { category: string }) {
  return <Badge className="bg-surface-sunken text-muted ring-black/5 dark:ring-white/10">{titleCase(category)}</Badge>;
}

export function StanceChip({ stance }: { stance: string }) {
  const cls =
    stance === "supports"
      ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-500/10 dark:text-emerald-300"
      : stance === "contradicts"
        ? "bg-rose-50 text-rose-700 ring-rose-600/20 dark:bg-rose-500/10 dark:text-rose-300"
        : "bg-surface-sunken text-subtle ring-transparent";
  return <Badge className={cls}>{stance}</Badge>;
}

export function StatusDot({ status }: { status?: string | null }) {
  const color =
    status === "error" || status === "failed" || status === "dead_letter"
      ? "bg-red-500"
      : status === "running"
        ? "bg-amber-400 animate-pulse"
        : status === "changed" || status === "succeeded"
          ? "bg-emerald-500"
          : "bg-slate-300 dark:bg-slate-600";
  return <span className={cn("inline-block size-2 rounded-full", color)} />;
}

export function ThreatTier({ tier }: { tier: number }) {
  return (
    <span className="inline-flex items-center gap-0.5" title={`Threat tier ${tier}/5`} aria-label={`Threat tier ${tier} of 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <span
          key={i}
          className={cn(
            "h-3 w-1.5 rounded-sm",
            i <= tier ? (tier >= 4 ? "bg-red-500" : tier === 3 ? "bg-orange-400" : "bg-sky-400") : "bg-surface-sunken",
          )}
        />
      ))}
    </span>
  );
}
