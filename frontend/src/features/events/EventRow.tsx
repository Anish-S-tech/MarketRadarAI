import { Link } from "react-router-dom";
import type { EventOut } from "@/api/client";
import { CategoryBadge, ConfidenceBadge, PRIORITY_DOT, PriorityBadge, SimulatedBadge } from "@/components/ui/badges";
import { cn, timeAgo } from "@/lib/format";

export function EventRow({ event, compact }: { event: EventOut; compact?: boolean }) {
  return (
    <Link
      to={`/events/${event.id}`}
      className="group flex items-start gap-3 px-5 py-3 transition-colors hover:bg-surface-sunken/60"
    >
      <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", PRIORITY_DOT[event.priority ?? "low"])} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-default group-hover:underline">{event.title}</p>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted">
          <span className="font-medium text-default/80">{event.competitor_name}</span>
          <span className="text-subtle">·</span>
          {event.is_simulated && <SimulatedBadge />}
          <CategoryBadge category={event.category} />
          {!compact && <ConfidenceBadge level={event.confidence_level} score={event.confidence_score} />}
          {event.status !== "new" && <span className="text-subtle">· {event.status}</span>}
        </div>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <PriorityBadge priority={event.priority} />
        <span className="text-xs text-subtle">{timeAgo(event.detected_at)}</span>
      </div>
    </Link>
  );
}
