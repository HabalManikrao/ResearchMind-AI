import { useCallback, useEffect, useState } from "react";
import { FlaskConical, Lightbulb, Plus, Trash2 } from "lucide-react";
import { api } from "../api/client";
import type { Hypothesis, HypothesisStatus, Method, MethodStatus } from "../api/types";
import { Card } from "./ui";

const METHOD_STATUSES: MethodStatus[] = ["proposed", "active", "deprecated", "superseded"];
const HYP_STATUSES: HypothesisStatus[] = [
  "proposed", "testing", "supported", "partially_supported", "rejected", "inconclusive",
];

const METHOD_STATUS_CLS: Record<MethodStatus, string> = {
  proposed: "bg-slate-100 text-slate-600",
  active: "bg-green-100 text-green-700",
  deprecated: "bg-amber-100 text-amber-700",
  superseded: "bg-slate-200 text-slate-500",
};
const HYP_STATUS_CLS: Record<HypothesisStatus, string> = {
  proposed: "bg-indigo-100 text-indigo-700",
  testing: "bg-blue-100 text-blue-700",
  supported: "bg-green-100 text-green-700",
  partially_supported: "bg-teal-100 text-teal-700",
  rejected: "bg-red-100 text-red-700",
  inconclusive: "bg-slate-100 text-slate-600",
};
const HYP_LABEL: Record<HypothesisStatus, string> = {
  proposed: "Proposed",
  testing: "Testing",
  supported: "Supported",
  partially_supported: "Partially supported",
  rejected: "Rejected",
  inconclusive: "Inconclusive",
};

const inputCls =
  "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500";
const btnCls =
  "inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60";
const selCls =
  "rounded-md border border-slate-300 bg-white px-1.5 py-1 text-xs text-slate-600 focus:outline-none";

/**
 * R&D layer Phase B — Methods (the *how*) and Hypotheses (propositions awaiting validation).
 * A Hypothesis is visually distinct from a Claim: a PROPOSED hypothesis is explicitly labelled
 * "Not yet validated", and rejected hypotheses stay visible (historical research knowledge).
 */
export default function LabPanel({ projectId }: { projectId: string }) {
  const [methods, setMethods] = useState<Method[]>([]);
  const [hyps, setHyps] = useState<Hypothesis[]>([]);

  const load = useCallback(async () => {
    const [m, h] = await Promise.all([api.methods(projectId), api.hypotheses(projectId)]);
    setMethods(m);
    setHyps(h);
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-6">
      {/* --- Methods --- */}
      <Card>
        <div className="mb-1 flex items-center gap-2">
          <FlaskConical className="h-5 w-5 text-brand-600" />
          <h2 className="text-lg font-semibold text-slate-900">Methods</h2>
        </div>
        <p className="mb-3 text-xs text-slate-500">
          Reusable approaches used to investigate or test — not evidence, not results.
        </p>
        {methods.length === 0 ? (
          <p className="mb-3 text-sm text-slate-500">No methods yet.</p>
        ) : (
          <ul className="mb-3 space-y-2">
            {methods.map((m) => (
              <li key={m.id} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-slate-900">{m.name}</span>
                      <span className={`rounded px-1.5 py-0.5 text-xs ${METHOD_STATUS_CLS[m.status]}`}>
                        {m.status}
                      </span>
                      <span className="text-xs text-slate-400">v{m.version}</span>
                    </div>
                    {m.description && <p className="mt-1 text-sm text-slate-600">{m.description}</p>}
                    {m.procedure && (
                      <p className="mt-1 text-xs text-slate-500">Procedure: {m.procedure}</p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <select
                      className={selCls}
                      aria-label={`Status for ${m.name}`}
                      value={m.status}
                      onChange={async (e) => {
                        const updated = await api.updateMethod(projectId, m.id, {
                          status: e.target.value as MethodStatus,
                        });
                        setMethods((xs) => xs.map((x) => (x.id === m.id ? updated : x)));
                      }}
                    >
                      {METHOD_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                    <button
                      title="Delete method"
                      onClick={async () => {
                        await api.deleteMethod(projectId, m.id);
                        setMethods((xs) => xs.filter((x) => x.id !== m.id));
                      }}
                      className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
        <MethodAdder
          onAdd={async (name, description) => {
            const created = await api.createMethod(projectId, { name, description });
            setMethods((xs) => [...xs, created]);
          }}
        />
      </Card>

      {/* --- Hypotheses --- */}
      <Card>
        <div className="mb-1 flex items-center gap-2">
          <Lightbulb className="h-5 w-5 text-indigo-600" />
          <h2 className="text-lg font-semibold text-slate-900">Hypotheses</h2>
        </div>
        <p className="mb-3 text-xs text-slate-500">
          Propositions awaiting validation — <strong>not</strong> claims. A claim is evidence-backed;
          a hypothesis must be tested.
        </p>
        {hyps.length === 0 ? (
          <p className="mb-3 text-sm text-slate-500">No hypotheses yet.</p>
        ) : (
          <ul className="mb-3 space-y-2">
            {hyps.map((h) => (
              <li key={h.id} className="rounded-lg border border-indigo-100 bg-indigo-50/40 p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded px-1.5 py-0.5 text-xs ${HYP_STATUS_CLS[h.status]}`}>
                        {HYP_LABEL[h.status]}
                      </span>
                      {h.status === "proposed" && (
                        <span className="text-xs font-medium text-indigo-500">Not yet validated</span>
                      )}
                      {h.confidence != null && (
                        <span className="text-xs text-slate-500">confidence {h.confidence}%</span>
                      )}
                    </div>
                    <p className="mt-1 text-sm text-slate-800">{h.statement}</p>
                    {h.reasoning && <p className="mt-1 text-xs text-slate-500">Why: {h.reasoning}</p>}
                    {h.expected_result && (
                      <p className="mt-1 text-xs text-slate-500">Expected: {h.expected_result}</p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <select
                      className={selCls}
                      aria-label={`Status for hypothesis`}
                      value={h.status}
                      onChange={async (e) => {
                        const updated = await api.updateHypothesis(projectId, h.id, {
                          status: e.target.value as HypothesisStatus,
                        });
                        setHyps((xs) => xs.map((x) => (x.id === h.id ? updated : x)));
                      }}
                    >
                      {HYP_STATUSES.map((s) => <option key={s} value={s}>{HYP_LABEL[s]}</option>)}
                    </select>
                    <button
                      title="Delete hypothesis"
                      onClick={async () => {
                        await api.deleteHypothesis(projectId, h.id);
                        setHyps((xs) => xs.filter((x) => x.id !== h.id));
                      }}
                      className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
        <HypothesisAdder
          onAdd={async (statement, reasoning) => {
            const created = await api.createHypothesis(projectId, { statement, reasoning });
            setHyps((xs) => [...xs, created]);
          }}
        />
      </Card>
    </div>
  );
}

function MethodAdder({ onAdd }: { onAdd: (name: string, description: string) => Promise<void> }) {
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  return (
    <div className="flex gap-2">
      <input className={inputCls + " max-w-[14rem]"} placeholder="Method name…" value={name}
        onChange={(e) => setName(e.target.value)} />
      <input className={inputCls} placeholder="Description…" value={desc}
        onChange={(e) => setDesc(e.target.value)} />
      <button className={btnCls} disabled={!name.trim()}
        onClick={async () => { await onAdd(name.trim(), desc.trim()); setName(""); setDesc(""); }}>
        <Plus className="h-4 w-4" /> Add
      </button>
    </div>
  );
}

function HypothesisAdder({
  onAdd,
}: {
  onAdd: (statement: string, reasoning: string) => Promise<void>;
}) {
  const [stmt, setStmt] = useState("");
  const [why, setWhy] = useState("");
  return (
    <div className="flex gap-2">
      <input className={inputCls} placeholder="Hypothesis statement…" value={stmt}
        onChange={(e) => setStmt(e.target.value)} />
      <input className={inputCls + " max-w-[12rem]"} placeholder="Reasoning…" value={why}
        onChange={(e) => setWhy(e.target.value)} />
      <button className={btnCls} disabled={stmt.trim().length < 3}
        onClick={async () => { await onAdd(stmt.trim(), why.trim()); setStmt(""); setWhy(""); }}>
        <Plus className="h-4 w-4" /> Add
      </button>
    </div>
  );
}
