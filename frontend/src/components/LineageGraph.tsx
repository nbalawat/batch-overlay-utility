import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import { useMemo } from "react";
import type { Dependency, Graph, JobBrief } from "../api/types";
import { SCHEDULER_VENDOR, STATUS_META, VENDORS, hhmm } from "../lib/format";

const W = 176, H = 60;

type JobNodeData = { job: JobBrief; dim: boolean };

function JobNode({ data }: NodeProps<Node<JobNodeData>>) {
  const { job, dim } = data;
  const v = VENDORS[job.vendor];
  const s = STATUS_META[job.status];
  return (
    <div className={`gnode ${job.critical ? "gnode-critical" : ""} ${dim ? "gnode-dim" : ""} ${job.anomalous ? "gnode-anom" : ""}`}
      style={{ ["--vc" as string]: v.color }} title={job.id}>
      <Handle type="target" position={Position.Left} />
      <div className="gnode-top">
        <span className="gnode-vendor">{v.code}</span>
        <span className="gnode-container">{job.container}</span>
        <span className={`gnode-status tone-text-${s.tone}`} aria-label={s.label}>{s.icon}</span>
      </div>
      <div className="gnode-name">{job.name}</div>
      <div className="gnode-meta">
        {job.status === "succeeded" ? `ended ${hhmm(job.end)}` :
          job.projected_end ? `ETA ${hhmm(job.projected_end)}` : s.label}
        {job.failed_attempts > 0 && <span className="tone-text-critical"> · {job.failed_attempts} failed</span>}
        {job.anomalous && <span className="tone-text-warning"> · slow</span>}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = { job: JobNode, lane: LaneNode };

const LANE_ORDER = ["ctm-prd", "autosys-ae1", "airflow-dp", "adf-prd"];
const LANE_PAD = 34, GAP = 14, LANE_LABEL_W = 0;

/** Swimlane layout: x from the dependency rank (dagre), one horizontal lane per scheduler.
 *  Edges that cross lanes are exactly the cross-scheduler dependencies. */
function layout(nodes: JobBrief[], edges: Dependency[]) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 14, ranksep: 34, marginx: 10, marginy: 10 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => g.setNode(n.id, { width: W, height: H }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  const lanes = LANE_ORDER.filter((l) => nodes.some((n) => n.scheduler_id === l));
  const pos: Record<string, { x: number; y: number }> = {};
  const laneBoxes: { id: string; y: number; h: number }[] = [];
  let y0 = 0;
  for (const lane of lanes) {
    const members = nodes.filter((n) => n.scheduler_id === lane)
      .map((n) => ({ n, x: g.node(n.id).x - W / 2, y: g.node(n.id).y }));
    // Pack nodes into rows so nodes sharing an x-range never overlap.
    const rows: number[][] = [];
    members.sort((a, b) => a.y - b.y || a.x - b.x);
    for (const m of members) {
      let r = rows.findIndex((row) => row.every((x) => Math.abs(x - m.x) >= W + 20));
      if (r < 0) { rows.push([]); r = rows.length - 1; }
      rows[r].push(m.x);
      pos[m.n.id] = { x: m.x + LANE_LABEL_W, y: y0 + LANE_PAD + r * (H + GAP) };
    }
    const h = LANE_PAD + rows.length * (H + GAP) + 6;
    laneBoxes.push({ id: lane, y: y0, h });
    y0 += h + 10;
  }
  const maxX = Math.max(...Object.values(pos).map((p) => p.x)) + W + 20;
  return { pos, laneBoxes, width: maxX, height: y0 };
}

type LaneData = { label: string; color: string; width: number; height: number };
function LaneNode({ data }: NodeProps<Node<LaneData>>) {
  return (
    <div className="lane" style={{ width: data.width, height: data.height, ["--vc" as string]: data.color }}>
      <span className="lane-label">{data.label}</span>
    </div>
  );
}

export function edgeStyle(d: Dependency): Partial<Edge> {
  const inferred = d.origin === "inferred";
  const stroke = d.critical ? "var(--critical)" : d.cross_scheduler ? "var(--accent)" : "var(--edge)";
  return {
    animated: d.cross_scheduler && !inferred,
    style: { stroke, strokeWidth: d.cross_scheduler || d.critical ? 2.5 : 1.5,
      strokeDasharray: inferred ? "6 4" : undefined, opacity: d.active === false ? 0.35 : 1 },
    markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 16, height: 16 },
    label: d.cross_scheduler ? (inferred ? `inferred ${Math.round(d.confidence * 100)}%` :
      (d.artifact ?? "").replace(/^file:|^data:/, "")) : undefined,
    labelStyle: { fill: "var(--text-2)", fontSize: 10 },
    labelBgStyle: { fill: "var(--surface-2)" },
  };
}

export function LineageGraph({ graph, onSelect, highlight, maxHeight = 720, viewWidth = 1300 }: {
  graph: Graph; onSelect?: (id: string) => void; highlight?: Set<string> | null; maxHeight?: number; viewWidth?: number;
}) {
  const { nodes, edges, height } = useMemo(() => {
    const { pos, laneBoxes, width, height: gh } = layout(graph.nodes, graph.edges);
    // Size the canvas to the graph's aspect ratio so fit-to-view stays legible.
    const height = Math.min(maxHeight, Math.max(260, (gh / Math.max(width, 1)) * viewWidth + 60));
    const lanes: Node[] = laneBoxes.map((l) => {
      const v = VENDORS[SCHEDULER_VENDOR[l.id]];
      const sch = graph.schedulers.find((s) => s.id === l.id);
      return { id: `lane-${l.id}`, type: "lane", position: { x: -20, y: l.y }, selectable: false, draggable: false,
        zIndex: -1, data: { label: `${v.code} · ${sch?.name ?? l.id}`, color: v.color, width: width + 20, height: l.h } };
    });
    const nodes: Node[] = [...lanes, ...graph.nodes.map((j) => ({
      id: j.id, type: "job", position: pos[j.id], data: { job: j, dim: !!highlight && !highlight.has(j.id) },
    }))];
    const edges: Edge[] = graph.edges.map((d) => ({ id: d.id, source: d.source, target: d.target, ...edgeStyle(d) }));
    return { nodes, edges, height };
  }, [graph, highlight, maxHeight, viewWidth]);

  return (
    <div className="graph-wrap" style={{ height }}>
      <ReactFlow key={`${graph.nodes.length}-${height}`} nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.04 }} minZoom={0.2} maxZoom={1.6}
        proOptions={{ hideAttribution: true }} nodesDraggable={false} onNodeClick={(_, n) => n.type === "job" && onSelect?.(n.id)}>
        <Background color="var(--grid)" gap={24} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}

export function GraphLegend() {
  return (
    <div className="legend">
      {Object.values(VENDORS).map((v) => (
        <span key={v.code} className="vendor-tag" style={{ ["--vc" as string]: v.color }}>
          <span className="vendor-dot" />{v.code} = {v.label}
        </span>
      ))}
      <span className="legend-item"><span className="legend-line" style={{ background: "var(--accent)" }} />cross-scheduler link</span>
      <span className="legend-item"><span className="legend-line dashed" />inferred link (needs review)</span>
      <span className="legend-item"><span className="legend-line" style={{ background: "var(--critical)" }} />critical path</span>
    </div>
  );
}
