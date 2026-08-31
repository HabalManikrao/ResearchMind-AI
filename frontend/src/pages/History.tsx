import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ChevronRight } from "lucide-react";
import { api } from "../api/client";
import type { ProjectSummary } from "../api/types";
import { Badge, Card } from "../components/ui";

interface Investigation {
  rootId: string;
  runs: ProjectSummary[]; // newest first
  latest: ProjectSummary;
}

function groupByLineage(projects: ProjectSummary[]): Investigation[] {
  const byRoot = new Map<string, ProjectSummary[]>();
  for (const p of projects) {
    const root = p.root_id ?? p.id;
    const arr = byRoot.get(root) ?? [];
    arr.push(p);
    byRoot.set(root, arr);
  }
  const groups: Investigation[] = [];
  for (const [rootId, runs] of byRoot) {
    runs.sort((a, b) => (b.run_number ?? 1) - (a.run_number ?? 1));
    groups.push({ rootId, runs, latest: runs[0] });
  }
  // Newest investigation first (by its latest run's creation).
  groups.sort(
    (a, b) => new Date(b.latest.created_at).getTime() - new Date(a.latest.created_at).getTime()
  );
  return groups;
}

export default function History() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    api
      .listResearch()
      .then(setProjects)
      .finally(() => setLoading(false));
  }, []);

  const investigations = useMemo(() => groupByLineage(projects), [projects]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Research History</h1>
        <p className="text-slate-500">
          Grouped by investigation — each “Research Again” adds a run to its lineage.
        </p>
      </div>
      {loading ? (
        <p className="text-slate-500">Loading…</p>
      ) : investigations.length === 0 ? (
        <Card><p className="text-slate-500">No projects yet.</p></Card>
      ) : (
        <div className="space-y-2">
          {investigations.map((inv) => {
            const multi = inv.runs.length > 1;
            const open = expanded[inv.rootId];
            return (
              <Card key={inv.rootId} className="py-0">
                <div className="flex items-center justify-between gap-4 py-3">
                  <Link to={`/research/${inv.latest.id}`} className="min-w-0 flex-1">
                    <div className="truncate font-medium text-slate-900">{inv.latest.title}</div>
                    <div className="text-xs text-slate-400">
                      {new Date(inv.latest.created_at).toLocaleString()} · {inv.latest.mode}
                      {multi && ` · latest of ${inv.runs.length} runs`}
                    </div>
                  </Link>
                  <div className="flex shrink-0 items-center gap-2">
                    <Badge status={inv.latest.status} />
                    {multi && (
                      <button
                        onClick={() =>
                          setExpanded((e) => ({ ...e, [inv.rootId]: !e[inv.rootId] }))
                        }
                        className="rounded-lg border border-slate-200 p-1.5 text-slate-500 hover:bg-slate-100"
                        title={open ? "Hide runs" : "Show all runs"}
                      >
                        {open ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </button>
                    )}
                  </div>
                </div>

                {multi && open && (
                  <div className="border-t border-slate-100 py-2">
                    {inv.runs.map((r) => (
                      <Link
                        key={r.id}
                        to={`/research/${r.id}`}
                        className="flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-sm hover:bg-slate-50"
                      >
                        <span className="flex items-center gap-2">
                          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-semibold text-slate-600">
                            Run #{r.run_number ?? 1}
                          </span>
                          <span className="text-xs uppercase tracking-wide text-slate-400">
                            {r.run_intent ?? "original"}
                          </span>
                          <span className="text-xs text-slate-400">
                            {new Date(r.created_at).toLocaleDateString()}
                          </span>
                        </span>
                        <Badge status={r.status} />
                      </Link>
                    ))}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
