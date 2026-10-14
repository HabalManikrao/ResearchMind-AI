import { useCallback, useEffect, useState } from "react";
import { CircleCheck, Save } from "lucide-react";
import { api } from "../api/client";
import type { Reproducibility, ReproducibilityVerdict } from "../api/types";
import { Card } from "./ui";

const VERDICTS: ReproducibilityVerdict[] = [
  "not_assessed", "reproducible", "partially_reproducible", "not_reproducible", "inconclusive",
];
const VERDICT_LABEL: Record<ReproducibilityVerdict, string> = {
  not_assessed: "Not assessed",
  reproducible: "Reproducible",
  partially_reproducible: "Partially reproducible",
  not_reproducible: "Not reproducible",
  inconclusive: "Inconclusive",
};
const VERDICT_STYLE: Record<ReproducibilityVerdict, string> = {
  not_assessed: "bg-slate-100 text-slate-600",
  reproducible: "bg-green-100 text-green-700",
  partially_reproducible: "bg-amber-100 text-amber-700",
  not_reproducible: "bg-red-100 text-red-700",
  inconclusive: "bg-slate-100 text-slate-500",
};

const inputCls =
  "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500";
const btnCls =
  "inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60";

/**
 * R&D layer Phase F — reproducibility metadata + explicit verdict. Captured metadata is displayed
 * separately from the assessment; the verdict is only ever what was explicitly recorded (default
 * "Not assessed"), never inferred from complete metadata. Unavailable values are shown as "—".
 */
export default function ReproducibilityPanel({ projectId }: { projectId: string }) {
  const [rec, setRec] = useState<Reproducibility | null>(null);
  const [verdict, setVerdict] = useState<ReproducibilityVerdict>("not_assessed");
  const [rationale, setRationale] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    const r = await api.reproducibility(projectId);
    setRec(r);
    setVerdict(r.verdict);
    setRationale(r.rationale || "");
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  if (!rec) return <Card><p className="text-sm text-slate-500">Loading reproducibility…</p></Card>;

  const meta: [string, string | null | undefined][] = [
    ["Model", rec.model_name], ["Model version", rec.model_version],
    ["Provider", rec.model_provider], ["Embedding model", rec.embedding_model],
    ["Search provider", rec.search_provider], ["Provider config", rec.provider_config_id],
    ["Dataset version", rec.dataset_version], ["Seed", rec.seed], ["OS", rec.os],
    ["Hardware", rec.hardware], ["Environment", rec.environment],
    ["Git commit", rec.git_commit], ["Git branch", rec.git_branch],
    ["As of", rec.as_of], ["Captured by", rec.origin],
  ];

  const saveVerdict = async () => {
    setSaving(true);
    setSaved(false);
    try {
      const updated = await api.updateReproducibility(projectId, { verdict, rationale });
      setRec(updated);
      setSaved(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* --- Verdict (explicit assessment) --- */}
      <Card>
        <div className="mb-1 flex items-center gap-2">
          <CircleCheck className="h-5 w-5 text-brand-600" />
          <h2 className="text-lg font-semibold text-slate-900">Reproducibility Assessment</h2>
          <span className={`ml-1 rounded px-1.5 py-0.5 text-xs ${VERDICT_STYLE[rec.verdict]}`}>
            {VERDICT_LABEL[rec.verdict]}
          </span>
        </div>
        {rec.verdict === "not_assessed" && (
          <p className="mb-3 text-xs text-amber-700">
            Not assessed — the captured metadata below does <strong>not</strong> imply the research was
            reproduced. Record an explicit verdict only with a real assessment basis.
          </p>
        )}
        <label className="mb-1 block text-xs font-medium text-slate-600">Verdict</label>
        <select
          className={inputCls + " mb-3 max-w-xs"}
          aria-label="Reproducibility verdict"
          value={verdict}
          onChange={(e) => setVerdict(e.target.value as ReproducibilityVerdict)}
        >
          {VERDICTS.map((v) => <option key={v} value={v}>{VERDICT_LABEL[v]}</option>)}
        </select>
        <label className="mb-1 block text-xs font-medium text-slate-600">Rationale / basis</label>
        <textarea className={inputCls + " mb-3"} rows={2} value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          placeholder="Why this verdict? (evidence / what was actually reproduced)" />
        <div className="flex items-center gap-3">
          <button onClick={saveVerdict} disabled={saving} className={btnCls}>
            <Save className="h-4 w-4" /> {saving ? "Saving…" : "Save assessment"}
          </button>
          {saved && <span className="text-xs text-green-600">Saved</span>}
        </div>
      </Card>

      {/* --- Captured metadata (distinct from the assessment) --- */}
      <Card>
        <h2 className="mb-1 text-lg font-semibold text-slate-900">Captured Metadata</h2>
        <p className="mb-3 text-xs text-slate-500">
          Safe, non-secret identifiers captured for this run. "—" means unavailable (never fabricated).
        </p>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
          {meta.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-3 border-b border-slate-100 py-1">
              <dt className="text-xs text-slate-500">{k}</dt>
              <dd className="text-xs font-medium text-slate-800">{v || "—"}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </div>
  );
}
