import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ProjectSummary } from "../api/types";
import { Badge, Card, ProgressBar, Stat } from "../components/ui";
import { Plus } from "lucide-react";

export default function Dashboard() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .listResearch()
      .then(setProjects)
      .finally(() => setLoading(false));
  }, []);

  const completed = projects.filter((p) => p.status === "completed").length;
  const running = projects.filter((p) =>
    ["running", "planning", "paused"].includes(p.status)
  ).length;

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Dashboard</h1>
          <p className="text-slate-500">Your autonomous research projects at a glance.</p>
        </div>
        <Link
          to="/new"
          className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          <Plus className="h-4 w-4" /> New Research
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Total Projects" value={projects.length} />
        <Stat label="Completed" value={completed} />
        <Stat label="In Progress" value={running} />
        <Stat
          label="Sources Analyzed"
          value={projects.reduce((n, p) => n + (p.status === "completed" ? 1 : 0), 0)}
        />
      </div>

      <div>
        <h2 className="mb-3 text-lg font-semibold text-slate-900">Recent Research</h2>
        {loading ? (
          <p className="text-slate-500">Loading…</p>
        ) : projects.length === 0 ? (
          <Card>
            <p className="text-slate-500">
              No research yet. Start your first project from{" "}
              <Link to="/new" className="text-brand-600 underline">
                New Research
              </Link>
              .
            </p>
          </Card>
        ) : (
          <div className="space-y-3">
            {projects.slice(0, 8).map((p) => (
              <Link key={p.id} to={`/research/${p.id}`}>
                <Card className="transition hover:border-brand-400">
                  <div className="flex items-center justify-between gap-4">
                    <div className="min-w-0">
                      <div className="truncate font-medium text-slate-900">{p.title}</div>
                      <div className="truncate text-sm text-slate-500">{p.query}</div>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      <span className="text-xs uppercase text-slate-400">{p.mode}</span>
                      <Badge status={p.status} />
                    </div>
                  </div>
                  {["running", "planning", "paused"].includes(p.status) && (
                    <div className="mt-3">
                      <ProgressBar value={p.progress} />
                      <div className="mt-1 text-xs text-slate-500">
                        {p.progress}% · {p.current_stage ?? "…"}
                      </div>
                    </div>
                  )}
                </Card>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
