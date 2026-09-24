import { useCallback, useEffect, useState } from "react";
import { GitCompareArrows, Plus, ShieldAlert, HelpCircle, Trash2 } from "lucide-react";
import { api } from "../api/client";
import type {
  Comparison,
  GapStatus,
  KnowledgeGap,
  Limitation,
  LimitationSeverity,
  LimitationStatus,
  LimitationType,
} from "../api/types";
import { Card } from "./ui";

const LTYPES: LimitationType[] = [
  "source", "dataset", "method", "experiment", "technology", "research", "statistical", "environmental",
];
const LSEV: LimitationSeverity[] = ["high", "medium", "low"];
const LSTATUS: LimitationStatus[] = ["open", "mitigated", "accepted", "resolved"];
const GSTATUS: GapStatus[] = ["open", "investigating", "addressed", "wont_fix"];

const SEV_STYLE: Record<LimitationSeverity, string> = {
  high: "bg-red-100 text-red-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-slate-100 text-slate-600",
};
const gapLabel = (s?: string | null) => (s ? s.replace(/_/g, " ") : "open");

const inputCls =
  "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500";
const selCls =
  "rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-600 focus:outline-none";
const btnCls =
  "inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60 disabled:cursor-not-allowed";

/**
 * R&D layer Phase E — Comparisons (atomic, evidence-linked), Limitations (cross-cutting, traceable),
 * and Knowledge Gaps (open questions — never verified facts). An ungrounded comparison is flagged;
 * gaps are presented as open questions with status/importance, editable here.
 */
export default function SynthesisPanel({ projectId }: { projectId: string }) {
  const [comparisons, setComparisons] = useState<Comparison[]>([]);
  const [limitations, setLimitations] = useState<Limitation[]>([]);
  const [gaps, setGaps] = useState<KnowledgeGap[]>([]);

  const load = useCallback(async () => {
    const [c, l, g] = await Promise.all([
      api.comparisons(projectId),
      api.limitations(projectId),
      api.gaps(projectId),
    ]);
    setComparisons(c);
    setLimitations(l);
    setGaps(g);
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-6">
      {/* --- Comparisons --- */}
      <Card>
        <div className="mb-1 flex items-center gap-2">
          <GitCompareArrows className="h-5 w-5 text-brand-600" />
          <h2 className="text-lg font-semibold text-slate-900">Comparisons</h2>
        </div>
        <p className="mb-3 text-xs text-slate-500">
          Recorded comparison values. A value with no source/experiment/result is flagged ungrounded.
        </p>
        {comparisons.length === 0 ? (
          <p className="mb-3 text-sm text-slate-500">No comparisons yet.</p>
        ) : (
          <ul className="mb-3 space-y-2">
            {comparisons.map((c) => (
              <li key={c.id} className="flex items-start justify-between gap-2 rounded-lg border border-slate-200 p-3">
                <div className="min-w-0">
                  <span className="text-sm font-medium text-slate-900">
                    {c.subject_a}{c.subject_b ? ` vs. ${c.subject_b}` : ""}
                  </span>
                  {c.criterion && <span className="text-sm text-slate-600"> — {c.criterion}</span>}
                  <span className="text-sm text-slate-800">: {c.value}{c.unit ? ` ${c.unit}` : ""}</span>
                  {c.grounded ? (
                    <span className="ml-2 rounded bg-green-100 px-1.5 py-0.5 text-xs text-green-700">grounded</span>
                  ) : (
                    <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-700">ungrounded</span>
                  )}
                </div>
                <button title="Delete comparison"
                  onClick={async () => { await api.deleteComparison(projectId, c.id); setComparisons((xs) => xs.filter((x) => x.id !== c.id)); }}
                  className="shrink-0 rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600">
                  <Trash2 className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <ComparisonAdder onAdd={async (b) => {
          const created = await api.createComparison(projectId, b);
          setComparisons((xs) => [...xs, created]);
        }} />
      </Card>

      {/* --- Limitations --- */}
      <Card>
        <div className="mb-1 flex items-center gap-2">
          <ShieldAlert className="h-5 w-5 text-amber-600" />
          <h2 className="text-lg font-semibold text-slate-900">Limitations</h2>
        </div>
        <p className="mb-3 text-xs text-slate-500">
          Cross-cutting, traceable limitations across sources/datasets/methods/experiments/research.
        </p>
        {limitations.length === 0 ? (
          <p className="mb-3 text-sm text-slate-500">No limitations yet.</p>
        ) : (
          <ul className="mb-3 space-y-2">
            {limitations.map((l) => (
              <li key={l.id} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">{l.ltype}</span>
                      <span className={`rounded px-1.5 py-0.5 text-xs ${SEV_STYLE[l.severity]}`}>{l.severity}</span>
                      <span className="text-xs text-slate-400">status: {l.status}</span>
                    </div>
                    <p className="mt-1 text-sm text-slate-800">{l.title && <strong>{l.title} — </strong>}{l.description}</p>
                    {l.mitigation && <p className="mt-1 text-xs text-slate-500">Mitigation: {l.mitigation}</p>}
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <select className={selCls} aria-label="Limitation status" value={l.status}
                      onChange={async (e) => {
                        const upd = await api.updateLimitation(projectId, l.id, { status: e.target.value as LimitationStatus });
                        setLimitations((xs) => xs.map((x) => (x.id === l.id ? upd : x)));
                      }}>
                      {LSTATUS.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                    <button title="Delete limitation"
                      onClick={async () => { await api.deleteLimitation(projectId, l.id); setLimitations((xs) => xs.filter((x) => x.id !== l.id)); }}
                      className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
        <LimitationAdder onAdd={async (b) => {
          const created = await api.createLimitation(projectId, b);
          setLimitations((xs) => [...xs, created]);
        }} />
      </Card>

      {/* --- Knowledge Gaps --- */}
      <Card>
        <div className="mb-1 flex items-center gap-2">
          <HelpCircle className="h-5 w-5 text-indigo-600" />
          <h2 className="text-lg font-semibold text-slate-900">Knowledge Gaps</h2>
        </div>
        <p className="mb-3 text-xs text-slate-500">
          Open questions and missing knowledge — <strong>not</strong> verified findings.
        </p>
        {gaps.length === 0 ? (
          <p className="mb-3 text-sm text-slate-500">No knowledge gaps yet.</p>
        ) : (
          <ul className="mb-3 space-y-2">
            {gaps.map((g) => (
              <li key={g.id} className="rounded-lg border border-indigo-100 bg-indigo-50/40 p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded bg-indigo-100 px-1.5 py-0.5 text-xs text-indigo-700">
                        {gapLabel(g.status)}
                      </span>
                      <span className="text-xs font-medium text-indigo-500">Open question</span>
                      {g.importance && <span className="text-xs text-slate-500">importance: {g.importance}</span>}
                      {g.origin && <span className="text-xs text-slate-400">({g.origin})</span>}
                    </div>
                    <p className="mt-1 text-sm text-slate-800">{g.question}</p>
                    {g.potential_investigation && (
                      <p className="mt-1 text-xs text-slate-500">Investigate: {g.potential_investigation}</p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <select className={selCls} aria-label="Gap status" value={g.status ?? "open"}
                      onChange={async (e) => {
                        const upd = await api.updateGap(projectId, g.id, { status: e.target.value as GapStatus });
                        setGaps((xs) => xs.map((x) => (x.id === g.id ? upd : x)));
                      }}>
                      {GSTATUS.map((s) => <option key={s} value={s}>{gapLabel(s)}</option>)}
                    </select>
                    <button title="Delete gap"
                      onClick={async () => { await api.deleteGap(projectId, g.id); setGaps((xs) => xs.filter((x) => x.id !== g.id)); }}
                      className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
        <GapAdder onAdd={async (b) => {
          const created = await api.createGap(projectId, b);
          setGaps((xs) => [...xs, created]);
        }} />
      </Card>
    </div>
  );
}

function ComparisonAdder({ onAdd }: { onAdd: (b: Partial<Comparison>) => Promise<void> }) {
  const [a, setA] = useState("");
  const [crit, setCrit] = useState("");
  const [val, setVal] = useState("");
  return (
    <div className="flex flex-wrap gap-2">
      <input className={inputCls + " max-w-[12rem]"} placeholder="Subject…" value={a} onChange={(e) => setA(e.target.value)} />
      <input className={inputCls + " max-w-[10rem]"} placeholder="Criterion…" value={crit} onChange={(e) => setCrit(e.target.value)} />
      <input className={inputCls + " max-w-[8rem]"} placeholder="Value…" value={val} onChange={(e) => setVal(e.target.value)} />
      <button className={btnCls} disabled={!a.trim()}
        onClick={async () => { await onAdd({ subject_a: a.trim(), criterion: crit.trim(), value: val.trim() }); setA(""); setCrit(""); setVal(""); }}>
        <Plus className="h-4 w-4" /> Add
      </button>
    </div>
  );
}

function LimitationAdder({ onAdd }: { onAdd: (b: Partial<Limitation>) => Promise<void> }) {
  const [ltype, setLtype] = useState<LimitationType>("research");
  const [sev, setSev] = useState<LimitationSeverity>("medium");
  const [desc, setDesc] = useState("");
  return (
    <div className="flex flex-wrap gap-2">
      <select className={selCls} aria-label="New limitation type" value={ltype} onChange={(e) => setLtype(e.target.value as LimitationType)}>
        {LTYPES.map((t) => <option key={t} value={t}>{t}</option>)}
      </select>
      <select className={selCls} aria-label="New limitation severity" value={sev} onChange={(e) => setSev(e.target.value as LimitationSeverity)}>
        {LSEV.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
      <input className={inputCls + " min-w-[14rem] flex-1"} placeholder="Limitation description…" value={desc} onChange={(e) => setDesc(e.target.value)} />
      <button className={btnCls} disabled={desc.trim().length < 3}
        onClick={async () => { await onAdd({ ltype, severity: sev, description: desc.trim() }); setDesc(""); }}>
        <Plus className="h-4 w-4" /> Add
      </button>
    </div>
  );
}

function GapAdder({ onAdd }: { onAdd: (b: Partial<KnowledgeGap>) => Promise<void> }) {
  const [q, setQ] = useState("");
  const [imp, setImp] = useState("medium");
  return (
    <div className="flex flex-wrap gap-2">
      <input className={inputCls + " min-w-[16rem] flex-1"} placeholder="Open question / missing knowledge…" value={q} onChange={(e) => setQ(e.target.value)} />
      <select className={selCls} aria-label="New gap importance" value={imp} onChange={(e) => setImp(e.target.value)}>
        {["high", "medium", "low"].map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
      <button className={btnCls} disabled={q.trim().length < 3}
        onClick={async () => { await onAdd({ question: q.trim(), importance: imp }); setQ(""); }}>
        <Plus className="h-4 w-4" /> Add
      </button>
    </div>
  );
}
