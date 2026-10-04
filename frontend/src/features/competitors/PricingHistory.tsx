import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { PricePointOut } from "@/api/client";
import { Badge } from "@/components/ui/badges";
import { EmptyState } from "@/components/ui/primitives";
import { money } from "@/lib/format";

// Categorical palette (distinct in light and dark themes)
const SERIES = ["#0d9488", "#6366f1", "#ea7a0c", "#db2777", "#0284c7", "#65a30d", "#9333ea"];

const tooltipStyle = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  fontSize: 12,
  color: "var(--text)",
};

export function PricingHistory({ points }: { points: PricePointOut[] }) {
  if (!points.length) return <EmptyState title="No pricing observed yet">Add a pricing-page source to track price history.</EmptyState>;

  const plans = [...new Set(points.filter((p) => p.price !== null).map((p) => p.plan))];
  // Build a step series: one row per change timestamp, carrying forward each plan's current price.
  const times = [...new Set(points.flatMap((p) => [p.valid_from, ...(p.valid_to ? [p.valid_to] : [])]))].sort();
  times.push(new Date().toISOString());
  const rows = times.map((t) => {
    const row: Record<string, number | string | null> = { t };
    for (const plan of plans) {
      const active = points.find((p) => p.plan === plan && p.valid_from <= t && (!p.valid_to || p.valid_to > t));
      row[plan] = active?.price != null ? Number(active.price) : null;
    }
    return row;
  });
  const current = points.filter((p) => !p.valid_to);

  return (
    <div className="space-y-5">
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ left: 0, right: 12, top: 8 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis
              dataKey="t"
              tickFormatter={(t: string) => new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
              tick={{ fontSize: 11, fill: "var(--text-subtle)" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis tickFormatter={(v: number) => `$${v}`} tick={{ fontSize: 11, fill: "var(--text-subtle)" }} axisLine={false} tickLine={false} width={48} />
            <Tooltip contentStyle={tooltipStyle} labelFormatter={(t) => new Date(String(t)).toLocaleString()} formatter={(v) => money(v as number)} />
            <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />
            {plans.map((plan, i) => (
              <Line key={plan} type="stepAfter" dataKey={plan} stroke={SERIES[i % SERIES.length]} strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-subtle">
              <th className="py-2 pr-3 font-medium">Plan</th>
              <th className="py-2 pr-3 font-medium">Current price</th>
              <th className="py-2 pr-3 font-medium">Since</th>
              <th className="py-2 font-medium">Features</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-default">
            {current.map((p) => {
              const prev = points.filter((x) => x.plan === p.plan && x.valid_to).sort((a, b) => (a.valid_to! < b.valid_to! ? 1 : -1))[0];
              return (
                <tr key={p.id} className="align-top">
                  <td className="py-2 pr-3 font-medium">{p.plan}</td>
                  <td className="py-2 pr-3 tabular-nums">
                    {money(p.price, p.currency, p.period)}
                    {prev && <span className="ml-1.5 text-xs text-subtle line-through">{money(prev.price, prev.currency)}</span>}
                  </td>
                  <td className="py-2 pr-3 text-xs text-muted">{new Date(p.valid_from).toLocaleDateString()}</td>
                  <td className="py-2">
                    <div className="flex flex-wrap gap-1">
                      {p.features.map((f) => (
                        <Badge key={f}>{f}</Badge>
                      ))}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
