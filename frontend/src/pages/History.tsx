import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ProjectSummary } from "../api/types";
import { Badge, Card } from "../components/ui";

export default function History() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .listResearch()
      .then(setProjects)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Research History</h1>
        <p className="text-slate-500">All research projects, newest first.</p>
      </div>
      {loading ? (
        <p className="text-slate-500">Loading…</p>
      ) : projects.length === 0 ? (
        <Card><p className="text-slate-500">No projects yet.</p></Card>
      ) : (
        <div className="space-y-2">
          {projects.map((p) => (
            <Link key={p.id} to={`/research/${p.id}`}>
              <Card className="flex items-center justify-between gap-4 transition hover:border-brand-400">
                <div className="min-w-0">
                  <div className="truncate font-medium text-slate-900">{p.title}</div>
                  <div className="text-xs text-slate-400">
                    {new Date(p.created_at).toLocaleString()} · {p.mode}
                  </div>
                </div>
                <Badge status={p.status} />
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
