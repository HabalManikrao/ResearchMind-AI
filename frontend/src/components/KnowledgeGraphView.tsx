import { useMemo } from "react";
import type { KnowledgeGraph, GraphNode } from "../api/types";

const TYPE_COLOR: Record<string, string> = {
  project: "#4f46e5",
  solution: "#7c3aed",
  recommendation: "#0d9488",
  claim: "#2563eb",
  source: "#64748b",
};

const RING: Record<string, number> = {
  project: 0,
  solution: 120,
  recommendation: 120,
  claim: 210,
  source: 300,
};

interface Positioned extends GraphNode {
  x: number;
  y: number;
}

const W = 760;
const H = 600;
const CX = W / 2;
const CY = H / 2;

export default function KnowledgeGraphView({ graph }: { graph: KnowledgeGraph }) {
  const { positioned, byId } = useMemo(() => {
    // Group non-project nodes by ring radius, then spread each ring over a circle.
    const groups: Record<number, GraphNode[]> = {};
    let project: GraphNode | undefined;
    for (const n of graph.nodes) {
      if (n.type === "project") {
        project = n;
        continue;
      }
      const r = RING[n.type] ?? 300;
      (groups[r] ??= []).push(n);
    }
    const pos: Positioned[] = [];
    if (project) pos.push({ ...project, x: CX, y: CY });
    for (const [rStr, nodes] of Object.entries(groups)) {
      const r = Number(rStr);
      nodes.forEach((n, i) => {
        const angle = (i / nodes.length) * Math.PI * 2 - Math.PI / 2;
        pos.push({ ...n, x: CX + r * Math.cos(angle), y: CY + r * Math.sin(angle) });
      });
    }
    const map: Record<string, Positioned> = {};
    for (const p of pos) map[p.id] = p;
    return { positioned: pos, byId: map };
  }, [graph]);

  const types = Array.from(new Set(graph.nodes.map((n) => n.type)));

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-3 text-xs">
        {types.map((t) => (
          <span key={t} className="flex items-center gap-1.5 capitalize text-slate-600">
            <span
              className="inline-block h-3 w-3 rounded-full"
              style={{ background: TYPE_COLOR[t] ?? "#94a3b8" }}
            />
            {t}
          </span>
        ))}
      </div>
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-slate-50">
        <svg viewBox={`0 0 ${W} ${H}`} className="min-w-[760px]" role="img" aria-label="Knowledge graph">
          {graph.edges.map((e, i) => {
            const a = byId[e.source];
            const b = byId[e.target];
            if (!a || !b) return null;
            return (
              <line
                key={i}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke="#cbd5e1"
                strokeWidth={1}
              />
            );
          })}
          {positioned.map((n) => {
            const color = TYPE_COLOR[n.type] ?? "#94a3b8";
            const r = n.type === "project" ? 10 : n.recommended ? 8 : 6;
            const label = n.label.length > 26 ? n.label.slice(0, 26) + "…" : n.label;
            return (
              <g key={n.id}>
                <circle
                  cx={n.x}
                  cy={n.y}
                  r={r}
                  fill={color}
                  stroke={n.recommended ? "#f59e0b" : "#fff"}
                  strokeWidth={n.recommended ? 2.5 : 1.5}
                />
                <text
                  x={n.x}
                  y={n.y - r - 4}
                  textAnchor="middle"
                  className="fill-slate-700"
                  style={{ fontSize: 10 }}
                >
                  {label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
