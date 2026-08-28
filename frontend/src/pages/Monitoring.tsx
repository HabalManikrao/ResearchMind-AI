import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { AuditEntry, MonitoringStats } from "../api/types";
import { Card, Stat } from "../components/ui";

const ACTION_LABEL: Record<string, string> = {
  "research.create": "Created research",
  "research.start": "Started research",
  "research.stop": "Stopped research",
  "research.export": "Exported report",
};

export default function Monitoring() {
  const [stats, setStats] = useState<MonitoringStats | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);

  useEffect(() => {
    const load = () => {
      api.monitoringStats().then(setStats).catch(() => {});
      api.monitoringAudit().then(setAudit).catch(() => {});
    };
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Monitoring</h1>
        <p className="text-slate-500">System activity and the audit trail.</p>
      </div>

      {stats && (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <Stat label="Total Projects" value={stats.projects.total} />
          <Stat label="Active Runs" value={stats.projects.active_runs} />
          <Stat label="Sources Stored" value={stats.totals.sources} />
          <Stat label="Verified Claims" value={stats.totals.claims} />
        </div>
      )}

      {stats && (
        <Card>
          <h2 className="mb-3 text-lg font-semibold text-slate-900">Projects by Status</h2>
          <div className="flex flex-wrap gap-2">
            {Object.entries(stats.projects.by_status).map(([status, count]) => (
              <span
                key={status}
                className="rounded-full bg-slate-100 px-3 py-1 text-sm capitalize text-slate-700"
              >
                {status.replace(/_/g, " ")}: <span className="font-semibold">{count}</span>
              </span>
            ))}
          </div>
        </Card>
      )}

      <div>
        <h2 className="mb-3 text-lg font-semibold text-slate-900">Audit Log</h2>
        {audit.length === 0 ? (
          <Card><p className="text-sm text-slate-500">No activity recorded yet.</p></Card>
        ) : (
          <Card className="p-0">
            <table className="w-full text-sm">
              <thead className="border-b border-slate-200 text-left text-slate-500">
                <tr>
                  <th className="px-4 py-2 font-medium">Action</th>
                  <th className="px-4 py-2 font-medium">Details</th>
                  <th className="px-4 py-2 font-medium">IP</th>
                  <th className="px-4 py-2 font-medium">Time</th>
                </tr>
              </thead>
              <tbody>
                {audit.map((a) => (
                  <tr key={a.id} className="border-b border-slate-100">
                    <td className="px-4 py-2 text-slate-800">
                      {ACTION_LABEL[a.action] ?? a.action}
                    </td>
                    <td className="px-4 py-2 text-slate-500">
                      {Object.entries(a.detail || {})
                        .map(([k, v]) => `${k}: ${v}`)
                        .join(", ") || "—"}
                    </td>
                    <td className="px-4 py-2 text-slate-500">{a.client_ip ?? "—"}</td>
                    <td className="px-4 py-2 text-slate-400">
                      {new Date(a.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </div>
    </div>
  );
}
