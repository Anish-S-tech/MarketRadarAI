import { Background, Controls, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import type { RelationshipGraph as Graph } from "@/api/client";

const KIND_STYLE: Record<string, React.CSSProperties> = {
  us: { background: "#0f766e", color: "#fff", border: "none", fontWeight: 600 },
  competitor: { background: "#fff1f2", color: "#9f1239", border: "1px solid #fda4af", fontWeight: 600 },
  organization: { background: "var(--surface)", color: "var(--text)", border: "1px solid var(--border)" },
};

/** Radial layout: us in the centre, competitors on the inner ring, their counterparties on the outer ring. */
export function RelationshipGraph({ graph, height = 420 }: { graph: Graph; height?: number }) {
  const { nodes, edges } = useMemo(() => {
    const comps = graph.nodes.filter((n) => n.kind === "competitor");
    const orgs = graph.nodes.filter((n) => n.kind === "organization");
    const pos: Record<string, { x: number; y: number }> = { us: { x: 0, y: 0 } };
    comps.forEach((n, i) => {
      const a = (2 * Math.PI * i) / Math.max(comps.length, 1) - Math.PI / 2;
      pos[n.id] = { x: Math.cos(a) * 220, y: Math.sin(a) * 160 };
    });
    orgs.forEach((n, i) => {
      const a = (2 * Math.PI * i) / Math.max(orgs.length, 1) - Math.PI / 2 + 0.3;
      pos[n.id] = { x: Math.cos(a) * 420, y: Math.sin(a) * 280 };
    });
    const nodes: Node[] = graph.nodes.map((n) => ({
      id: n.id,
      position: pos[n.id] ?? { x: 0, y: 0 },
      data: { label: n.label },
      style: { ...KIND_STYLE[n.kind], borderRadius: 10, fontSize: 12, padding: "6px 10px", width: "auto" },
      draggable: true,
    }));
    const edges: Edge[] = graph.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.label === "competes with" ? undefined : e.label,
      animated: e.label !== "competes with",
      style: { stroke: e.label === "competes with" ? "var(--border)" : "#6366f1", strokeWidth: 1.5 },
      labelStyle: { fontSize: 10, fill: "var(--text-muted)" },
      labelBgStyle: { fill: "var(--surface)" },
    }));
    return { nodes, edges };
  }, [graph]);

  return (
    <div style={{ height }} className="overflow-hidden rounded-lg border border-default">
      <ReactFlow nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }} nodesConnectable={false}>
        <Background gap={20} color="var(--border)" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
