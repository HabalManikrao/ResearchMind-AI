import { useCallback, useEffect, useState } from "react";
import { Beaker, Database, LineChart, Plus, Trash2 } from "lucide-react";
import { api } from "../api/client";
import type { Dataset, Experiment, ExperimentStatus, Result } from "../api/types";
import { Card } from "./ui";

const EXP_STATUSES: ExperimentStatus[] = [
  "proposed", "planned", "running", "completed", "failed", "cancelled", "inconclusive",
];
const EXECUTED: ExperimentStatus[] = ["running", "completed", "failed", "inconclusive"];
const EXP_STATUS_CLS: Record<ExperimentStatus, string> = {
  proposed: "bg-slate-100 text-slate-600",
  planned: "bg-indigo-100 text-indigo-700",
  running: "bg-blue-100 text-blue-700",
  completed: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
  cancelled: "bg-slate-200 text-slate-500",
  inconclusive: "bg-amber-100 text-amber-700",
};

const inputCls =
  "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500";
const btnCls =
  "inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60";
const selCls =
  "rounded-md border border-slate-300 bg-white px-1.5 py-1 text-xs text-slate-600 focus:outline-none";

/**
 * R&D layer Phase C — Experiments, Datasets, Results. A PLANNED experiment is never shown as
 * executed: only executed statuses reveal execution fields, and a fresh experiment is labelled
 * "Not executed". Results display structured metric values (value + unit + bounds + conditions).
 */
export default function ExperimentsPanel({ projectId }: { projectId: string }) {
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [results, setResults] = useState<Result[]>([]);

  const load = useCallback(async () => {
    const [e, d, r] = await Promise.all([
      api.experiments(projectId),
      api.datasets(projectId),
      api.results(projectId),
    ]);
    setExperiments(e);
    setDatasets(d);
    setResults(r);
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-6">
      {/* --- Experiments --- */}
      <Card>
        <div className="mb-1 flex items-center gap-2">
          <Beaker className="h-5 w-5 text-brand-600" />
          <h2 className="text-lg font-semibold text-slate-900">Experiments</h2>
        </div>
        <p className="mb-3 text-xs text-slate-500">
          A planned experiment is a design, not a result — execution is recorded only when it
          actually happens.
        </p>
        {experiments.length === 0 ? (
          <p className="mb-3 text-sm text-slate-500">No experiments yet.</p>
        ) : (
          <ul className="mb-3 space-y-2">
            {experiments.map((e) => {
              const executed = EXECUTED.includes(e.status);
              return (
                <li key={e.id} className="rounded-lg border border-slate-200 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-slate-900">{e.name}</span>
                        <span className={`rounded px-1.5 py-0.5 text-xs ${EXP_STATUS_CLS[e.status]}`}>
                          {e.status}
                        </span>
                        {!executed && (
                          <span className="text-xs font-medium text-slate-400">Not executed</span>
                        )}
                      </div>
                      {e.description && <p className="mt-1 text-sm text-slate-600">{e.description}</p>}
                      {e.expected_result && (
                        <p className="mt-1 text-xs text-slate-500">Expected: {e.expected_result}</p>
                      )}
                      {/* Execution details ONLY when actually recorded. */}
                      {executed && e.actual_result_summary && (
                        <p className="mt-1 text-xs text-green-700">
                          Recorded outcome: {e.actual_result_summary}
                        </p>
                      )}
                      {executed && e.completed_at && (
                        <p className="mt-1 text-xs text-slate-500">Completed: {e.completed_at}</p>
                      )}
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <select
                        className={selCls}
                        aria-label={`Status for ${e.name}`}
                        value={e.status}
                        onChange={async (ev) => {
                          const upd = await api.updateExperiment(projectId, e.id, {
                            status: ev.target.value as ExperimentStatus,
                          });
                          setExperiments((xs) => xs.map((x) => (x.id === e.id ? upd : x)));
                        }}
                      >
                        {EXP_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                      </select>
                      <button
                        title="Delete experiment"
                        onClick={async () => {
                          await api.deleteExperiment(projectId, e.id);
                          setExperiments((xs) => xs.filter((x) => x.id !== e.id));
                          setResults((xs) => xs.filter((x) => x.experiment_id !== e.id));
                        }}
                        className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        <SimpleAdder
          placeholder="Experiment name…"
          onAdd={async (name) => {
            const created = await api.createExperiment(projectId, { name });
            setExperiments((xs) => [...xs, created]);
          }}
        />
      </Card>

      {/* --- Datasets --- */}
      <Card>
        <div className="mb-1 flex items-center gap-2">
          <Database className="h-5 w-5 text-teal-600" />
          <h2 className="text-lg font-semibold text-slate-900">Datasets</h2>
        </div>
        <p className="mb-3 text-xs text-slate-500">Version-distinguishable inputs; each version is retained.</p>
        {datasets.length === 0 ? (
          <p className="mb-3 text-sm text-slate-500">No datasets yet.</p>
        ) : (
          <ul className="mb-3 space-y-2">
            {datasets.map((d) => (
              <li key={d.id} className="flex items-start justify-between gap-2 rounded-lg border border-slate-200 p-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-slate-900">{d.name}</span>
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">v{d.version}</span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    {[d.source && `source: ${d.source}`, d.size && `size: ${d.size}`,
                      d.quality && `quality: ${d.quality}`].filter(Boolean).join(" · ")}
                  </p>
                  {d.limitations.length > 0 && (
                    <p className="mt-1 text-xs text-amber-700">Limitations: {d.limitations.join("; ")}</p>
                  )}
                  {d.access_information && (
                    <p className="mt-1 text-xs text-slate-500">Access: {d.access_information}</p>
                  )}
                </div>
                <button
                  title="Delete dataset"
                  onClick={async () => {
                    await api.deleteDataset(projectId, d.id);
                    setDatasets((xs) => xs.filter((x) => x.id !== d.id));
                  }}
                  className="shrink-0 rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <SimpleAdder
          placeholder="Dataset name…"
          onAdd={async (name) => {
            const created = await api.createDataset(projectId, { name });
            setDatasets((xs) => [...xs, created]);
          }}
        />
      </Card>

      {/* --- Results --- */}
      <Card>
        <div className="mb-1 flex items-center gap-2">
          <LineChart className="h-5 w-5 text-green-600" />
          <h2 className="text-lg font-semibold text-slate-900">Results</h2>
        </div>
        <p className="mb-3 text-xs text-slate-500">
          Structured, recorded outputs of an experiment — never generated automatically.
        </p>
        {results.length === 0 ? (
          <p className="text-sm text-slate-500">
            No results recorded. Results are added explicitly against an experiment.
          </p>
        ) : (
          <ul className="space-y-2">
            {results.map((r) => (
              <li key={r.id} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-slate-900">{r.name || r.result_type}</span>
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">{r.result_type}</span>
                  {r.confidence != null && (
                    <span className="text-xs text-slate-500">confidence {r.confidence}%</span>
                  )}
                </div>
                {r.metrics.length > 0 && (
                  <ul className="mt-1 text-xs text-slate-600">
                    {r.metrics.map((m, i) => (
                      <li key={i}>
                        {m.name}: {m.value ?? "—"}{m.unit ? ` ${m.unit}` : ""}
                        {m.lower_bound != null || m.upper_bound != null
                          ? ` [${m.lower_bound ?? "?"}–${m.upper_bound ?? "?"}]`
                          : ""}
                        {m.conditions ? ` (${m.conditions})` : ""}
                      </li>
                    ))}
                  </ul>
                )}
                {r.observations && <p className="mt-1 text-xs text-slate-500">Observations: {r.observations}</p>}
                {r.anomalies && <p className="mt-1 text-xs text-amber-700">Anomalies: {r.anomalies}</p>}
                {r.resource_usage && (
                  <p className="mt-1 text-xs text-slate-500">Resource usage: {r.resource_usage}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function SimpleAdder({
  placeholder,
  onAdd,
}: {
  placeholder: string;
  onAdd: (name: string) => Promise<void>;
}) {
  const [name, setName] = useState("");
  return (
    <div className="flex gap-2">
      <input className={inputCls} placeholder={placeholder} value={name}
        onChange={(e) => setName(e.target.value)} />
      <button className={btnCls} disabled={!name.trim()}
        onClick={async () => { await onAdd(name.trim()); setName(""); }}>
        <Plus className="h-4 w-4" /> Add
      </button>
    </div>
  );
}
