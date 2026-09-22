import { useCallback, useEffect, useState } from "react";
import { Microscope, Plus, ScrollText, Trash2 } from "lucide-react";
import { api } from "../api/client";
import type {
  Analysis,
  AnalysisClassification,
  Claim,
  Conclusion,
  ConclusionClassification,
} from "../api/types";
import { Card } from "./ui";

const ANALYSIS_CLS: AnalysisClassification[] = [
  "fact", "interpretation", "inference", "hypothesis", "opinion",
];
const CONCLUSION_CLS: ConclusionClassification[] = [
  "proven", "strongly_supported", "supported", "weakly_supported",
  "inconclusive", "unknown", "contradicted", "disproved",
];
const ANALYSIS_CLS_STYLE: Record<AnalysisClassification, string> = {
  fact: "bg-green-100 text-green-700",
  interpretation: "bg-blue-100 text-blue-700",
  inference: "bg-indigo-100 text-indigo-700",
  hypothesis: "bg-amber-100 text-amber-700",
  opinion: "bg-slate-100 text-slate-600",
};
const CONCLUSION_CLS_STYLE: Record<ConclusionClassification, string> = {
  proven: "bg-green-200 text-green-800",
  strongly_supported: "bg-green-100 text-green-700",
  supported: "bg-teal-100 text-teal-700",
  weakly_supported: "bg-amber-100 text-amber-700",
  inconclusive: "bg-slate-100 text-slate-600",
  unknown: "bg-slate-100 text-slate-500",
  contradicted: "bg-red-100 text-red-700",
  disproved: "bg-red-200 text-red-800",
};
const label = (s: string) => s.replace(/_/g, " ");

const inputCls =
  "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500";
const selCls =
  "rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-600 focus:outline-none";
const btnCls =
  "inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60 disabled:cursor-not-allowed";

/**
 * R&D layer Phase D — Analysis (classified, evidence-grounded) and Conclusions (classified,
 * traceable). Distinct from a Claim: an Analysis/Conclusion is an interpretation grounded in
 * existing claims/results, and its classification (e.g. FACT / INFERENCE / SUPPORTED) is explicit.
 * Grounding is REQUIRED — the create controls stay disabled until a claim/analysis is chosen, so the
 * UI can't create an ungrounded item.
 */
export default function AnalysisPanel({ projectId }: { projectId: string }) {
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [conclusions, setConclusions] = useState<Conclusion[]>([]);
  const [claims, setClaims] = useState<Claim[]>([]);

  const load = useCallback(async () => {
    const [a, c, cl] = await Promise.all([
      api.analyses(projectId),
      api.conclusions(projectId),
      api.claims(projectId),
    ]);
    setAnalyses(a);
    setConclusions(c);
    setClaims(cl);
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-6">
      {/* --- Analysis --- */}
      <Card>
        <div className="mb-1 flex items-center gap-2">
          <Microscope className="h-5 w-5 text-brand-600" />
          <h2 className="text-lg font-semibold text-slate-900">Analysis</h2>
        </div>
        <p className="mb-3 text-xs text-slate-500">
          Classified interpretations grounded in existing claims/results — a FACT label does not make
          it independently verified; the grounding does.
        </p>
        {analyses.length === 0 ? (
          <p className="mb-3 text-sm text-slate-500">No analysis yet.</p>
        ) : (
          <ul className="mb-3 space-y-2">
            {analyses.map((a) => (
              <li key={a.id} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded px-1.5 py-0.5 text-xs ${ANALYSIS_CLS_STYLE[a.classification]}`}>
                        {label(a.classification)}
                      </span>
                      {a.confidence != null && (
                        <span className="text-xs text-slate-500">confidence {a.confidence}%</span>
                      )}
                      <span className="text-xs text-slate-400">
                        {`grounded in ${a.claim_ids.length} claim(s), ${a.result_ids.length} result(s)`}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-slate-800">{a.title && <strong>{a.title} — </strong>}{a.statement}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <select
                      className={selCls}
                      aria-label="Analysis classification"
                      value={a.classification}
                      onChange={async (e) => {
                        const upd = await api.updateAnalysis(projectId, a.id, {
                          classification: e.target.value as AnalysisClassification,
                        });
                        setAnalyses((xs) => xs.map((x) => (x.id === a.id ? upd : x)));
                      }}
                    >
                      {ANALYSIS_CLS.map((c) => <option key={c} value={c}>{label(c)}</option>)}
                    </select>
                    <button
                      title="Delete analysis"
                      onClick={async () => {
                        await api.deleteAnalysis(projectId, a.id);
                        setAnalyses((xs) => xs.filter((x) => x.id !== a.id));
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
        <AnalysisAdder
          claims={claims}
          onAdd={async (statement, classification, claimId) => {
            const created = await api.createAnalysis(projectId, {
              statement, classification, claim_ids: [claimId],
            });
            setAnalyses((xs) => [...xs, created]);
          }}
        />
      </Card>

      {/* --- Conclusions --- */}
      <Card>
        <div className="mb-1 flex items-center gap-2">
          <ScrollText className="h-5 w-5 text-green-700" />
          <h2 className="text-lg font-semibold text-slate-900">Conclusions</h2>
        </div>
        <p className="mb-3 text-xs text-slate-500">
          Traceable to their analyses/claims. Classification is never auto-promoted; confidence is
          shown only when set.
        </p>
        {conclusions.length === 0 ? (
          <p className="mb-3 text-sm text-slate-500">No conclusions yet.</p>
        ) : (
          <ul className="mb-3 space-y-2">
            {conclusions.map((c) => (
              <li key={c.id} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded px-1.5 py-0.5 text-xs ${CONCLUSION_CLS_STYLE[c.classification]}`}>
                        {label(c.classification)}
                      </span>
                      {c.confidence != null && (
                        <span className="text-xs text-slate-500">confidence {c.confidence}%</span>
                      )}
                      <span className="text-xs text-slate-400">
                        {`from ${c.analysis_ids.length} analysis, ${c.claim_ids.length} claim(s)`}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-slate-800">{c.title && <strong>{c.title} — </strong>}{c.statement}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <select
                      className={selCls}
                      aria-label="Conclusion classification"
                      value={c.classification}
                      onChange={async (e) => {
                        const upd = await api.updateConclusion(projectId, c.id, {
                          classification: e.target.value as ConclusionClassification,
                        });
                        setConclusions((xs) => xs.map((x) => (x.id === c.id ? upd : x)));
                      }}
                    >
                      {CONCLUSION_CLS.map((k) => <option key={k} value={k}>{label(k)}</option>)}
                    </select>
                    <button
                      title="Delete conclusion"
                      onClick={async () => {
                        await api.deleteConclusion(projectId, c.id);
                        setConclusions((xs) => xs.filter((x) => x.id !== c.id));
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
        <ConclusionAdder
          analyses={analyses}
          onAdd={async (statement, classification, analysisId) => {
            const created = await api.createConclusion(projectId, {
              statement, classification, analysis_ids: [analysisId],
            });
            setConclusions((xs) => [...xs, created]);
          }}
        />
      </Card>
    </div>
  );
}

function AnalysisAdder({
  claims,
  onAdd,
}: {
  claims: Claim[];
  onAdd: (s: string, c: AnalysisClassification, claimId: string) => Promise<void>;
}) {
  const [statement, setStatement] = useState("");
  const [cls, setCls] = useState<AnalysisClassification>("interpretation");
  const [claimId, setClaimId] = useState("");
  const ready = statement.trim().length >= 3 && claimId !== "";
  if (claims.length === 0) {
    return (
      <p className="text-xs text-slate-400">
        Add analysis once claims exist — an analysis must be grounded in evidence.
      </p>
    );
  }
  return (
    <div className="flex flex-wrap gap-2">
      <input className={inputCls + " min-w-[16rem] flex-1"} placeholder="Analysis statement…"
        value={statement} onChange={(e) => setStatement(e.target.value)} />
      <select className={selCls} aria-label="New analysis classification" value={cls}
        onChange={(e) => setCls(e.target.value as AnalysisClassification)}>
        {ANALYSIS_CLS.map((c) => <option key={c} value={c}>{label(c)}</option>)}
      </select>
      <select className={selCls} aria-label="Ground in claim" value={claimId}
        onChange={(e) => setClaimId(e.target.value)}>
        <option value="">Ground in claim…</option>
        {claims.map((c) => <option key={c.id} value={c.id}>{c.text.slice(0, 40)}</option>)}
      </select>
      <button className={btnCls} disabled={!ready}
        onClick={async () => { await onAdd(statement.trim(), cls, claimId); setStatement(""); setClaimId(""); }}>
        <Plus className="h-4 w-4" /> Add
      </button>
    </div>
  );
}

function ConclusionAdder({
  analyses,
  onAdd,
}: {
  analyses: Analysis[];
  onAdd: (s: string, c: ConclusionClassification, analysisId: string) => Promise<void>;
}) {
  const [statement, setStatement] = useState("");
  const [cls, setCls] = useState<ConclusionClassification>("inconclusive");
  const [analysisId, setAnalysisId] = useState("");
  const ready = statement.trim().length >= 3 && analysisId !== "";
  if (analyses.length === 0) {
    return (
      <p className="text-xs text-slate-400">
        Add a conclusion once analysis exists — a conclusion must rest on an analysis or claim.
      </p>
    );
  }
  return (
    <div className="flex flex-wrap gap-2">
      <input className={inputCls + " min-w-[16rem] flex-1"} placeholder="Conclusion statement…"
        value={statement} onChange={(e) => setStatement(e.target.value)} />
      <select className={selCls} aria-label="New conclusion classification" value={cls}
        onChange={(e) => setCls(e.target.value as ConclusionClassification)}>
        {CONCLUSION_CLS.map((c) => <option key={c} value={c}>{label(c)}</option>)}
      </select>
      <select className={selCls} aria-label="Based on analysis" value={analysisId}
        onChange={(e) => setAnalysisId(e.target.value)}>
        <option value="">Based on analysis…</option>
        {analyses.map((a) => <option key={a.id} value={a.id}>{a.statement.slice(0, 40)}</option>)}
      </select>
      <button className={btnCls} disabled={!ready}
        onClick={async () => { await onAdd(statement.trim(), cls, analysisId); setStatement(""); setAnalysisId(""); }}>
        <Plus className="h-4 w-4" /> Add
      </button>
    </div>
  );
}
