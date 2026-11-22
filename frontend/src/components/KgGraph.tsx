import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import { useMemo } from "react";
import type { KgEdge, KgNode } from "../api/types";

/** Node types share one hue per family; the type name is always printed in the node (secondary encoding). */
export const NODE_STYLE: Record<string, { color: string; code: string }> = {
  Scheduler: { color: "var(--series-neutral)", code: "SCHED" },
  Container: { color: "var(--series-neutral)", code: "CONT" },
  Job: { color: "var(--accent)", code: "JOB" },
  Schedule: { color: "var(--series-neutral)", code: "WHEN" },
  Host: { color: "var(--v-adf)", code: "HOST" },
  Application: { color: "var(--series-neutral)", code: "APP" },
  Team: { color: "var(--v-af)", code: "TEAM" },
  File: { color: "var(--v-ctm)", code: "FILE" },
  Dataset: { color: "var(--v-ctm)", code: "DATA" },
  Queue: { color: "var(--v-ctm)", code: "QUEUE" },
  Event: { color: "var(--v-ctm)", code: "EVENT" },
  Endpoint: { color: "var(--v-asys)", code: "ENDPT" },
  Communication: { color: "var(--v-asys)", code: "MAIL" },
  BusinessProcess: { color: "var(--warning)", code: "PROC" },
  Service: { color: "var(--warning)", code: "SVC" },
  Incident: { color: "var(--critical)", code: "INC" },
};

const W = 190, H = 46;
type KData = { n: KgNode; center: boolean; dim: boolean };

function KNode({ data }: NodeProps<Node<KData>>) {
  const st = NODE_STYLE[data.n.type] ?? { color: "var(--edge)", code: data.n.type };
  const ext = data.n.type === "Endpoint" && data.n.props.internal === false;
  return (
    <div className={`knode ${data.center ? "knode-center" : ""} ${data.dim ? "gnode-dim" : ""}`}
      style={{ ["--vc" as string]: st.color }} title={data.n.id}>
      <Handle type="target" position={Position.Left} />
      <div className="knode-type">{st.code}{ext && <span className="tone-text-critical"> · external</span>}
        {data.n.type === "Job" && typeof data.n.props.vendor === "string" && <span className="muted"> · {String(data.n.props.vendor)}</span>}</div>
      <div className="knode-label">{data.n.label}</div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { k: KNode };

const PROV_STROKE: Record<string, string> = {
  proposed: "var(--warning)", approved: "var(--accent)", code: "var(--v-ctm)", runtime: "var(--v-adf)",
};

function stroke(e: KgEdge): string {
  for (const p of ["proposed", "approved", "code", "runtime"]) if (e.provenance.includes(p)) return PROV_STROKE[p];
  return "var(--edge)";
}

export function KgGraph({ nodes, edges, center, onSelect, highlight, height = 560 }: {
  nodes: KgNode[]; edges: KgEdge[]; center?: string; onSelect?: (id: string) => void; highlight?: Set<string> | null; height?: number;
}) {
  const flow = useMemo(() => {
    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: "LR", nodesep: 10, ranksep: 70, marginx: 10, marginy: 10 });
    g.setDefaultEdgeLabel(() => ({}));
    nodes.forEach((n) => g.setNode(n.id, { width: W, height: H }));
    edges.forEach((e) => g.setEdge(e.source, e.target));
    dagre.layout(g);
    const ns: Node[] = nodes.map((n) => ({
      id: n.id, type: "k", position: { x: g.node(n.id).x - W / 2, y: g.node(n.id).y - H / 2 },
      data: { n, center: n.id === center, dim: !!highlight && !highlight.has(n.id) },
    }));
    const es: Edge[] = edges.map((e) => {
      const s = stroke(e);
      return {
        id: e.id, source: e.source, target: e.target, label: e.type.toLowerCase().replace("_", " "),
        style: { stroke: s, strokeWidth: 1.6, strokeDasharray: e.provenance.includes("proposed") ? "6 4" : undefined },
        markerEnd: { type: MarkerType.ArrowClosed, color: s, width: 14, height: 14 },
        labelStyle: { fill: "var(--text-2)", fontSize: 10 }, labelBgStyle: { fill: "var(--surface-2)" },
      };
    });
    return { ns, es };
  }, [nodes, edges, center, highlight]);
  return (
    <div className="graph-wrap" style={{ height }} data-testid="kg-graph">
      <ReactFlow key={`${center}-${nodes.length}`} nodes={flow.ns} edges={flow.es} nodeTypes={nodeTypes} fitView
        fitViewOptions={{ padding: 0.05 }} minZoom={0.15} maxZoom={1.6} proOptions={{ hideAttribution: true }}
        nodesDraggable={false} onNodeClick={(_, n) => onSelect?.(n.id)}>
        <Background color="var(--grid)" gap={24} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}

export function ProvenanceLegend() {
  return (
    <div className="legend">
      {[["definition", "var(--edge)"], ["code", PROV_STROKE.code], ["runtime", PROV_STROKE.runtime],
        ["approved link", PROV_STROKE.approved]].map(([l, c]) => (
        <span key={l} className="legend-item"><span className="legend-line" style={{ background: c }} />{l}</span>
      ))}
      <span className="legend-item"><span className="legend-line" style={{ background: "repeating-linear-gradient(90deg, var(--warning) 0 6px, transparent 6px 10px)" }} />proposed link (in review)</span>
    </div>
  );
}
