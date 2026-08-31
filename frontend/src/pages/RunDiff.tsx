import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ChevronDown, ChevronRight, ArrowRight, ArrowLeft } from "lucide-react";
import { api } from "../api/client";
import type {
  ClaimDiffItem,
  DiffEvidenceItem,
  DiffKind,
  ResearchDiff,
} from "../api/types";
import { Card } from "../components/ui";

const KIND_STYLE: Record<string, string> = {
  new: "bg-emerald-100 text-emerald-700",
  removed: "bg-slate-200 text-slate-600",
  changed: "bg-amber-100 text-amber-700",
  strengthened: "bg-emerald-100 text-emerald-700",
  weakened: "bg-orange-100 text-orange-700",
  contradicted: "bg-red-100 text-red-700",
  unchanged: "bg-slate-100 text-slate-500",
  reversed: "bg-red-100 text-red-700",
  modified: "bg-amber-100 text-amber-700",
};

function KindBadge({ kind }: { kind: DiffKind }) {
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-xs font-semibold uppercase ${
        KIND_STYLE[kind] ?? "bg-slate-100 text-slate-600"
      }`}
    >
      {kind}
    </span>
  );
}

export default function RunDiff() {
  const { id, otherId } = useParams<{ id: string; otherId: string }>();
  const [diff, setDiff] = useState<ResearchDiff | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id || !otherId) return;
    api
      .diff(id, otherId)
      .then(setDiff)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load diff"));
  }, [id, otherId]);

  if (error) return <Card><p className="text-sm text-red-600">{error}</p></Card>;
  if (!diff) return <p className="text-slate-500">Loading changes…</p>;

  const { sources, claims, confidence, recommendation, documents } = diff;

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/research/${diff.new_run.id}`} className="text-sm text-brand-700 hover:underline">
          ← Back to run
        </Link>
        <h1 className="mt-1 text-2xl font-bold text-slate-900">Research Changes</h1>
        <p className="mt-1 flex items-center gap-2 text-slate-500">
          Run #{diff.old_run.run_number}
          <ArrowRight className="h-4 w-4" />
          Run #{diff.new_run.run_number}
        </p>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <SummaryCard title="Sources">
          <Delta plus={sources.new} minus={sources.removed} tilde={sources.changed} />
        </SummaryCard>
        <SummaryCard title="Claims">
          <Delta plus={claims.new} minus={claims.removed} tilde={claims.strengthened + claims.weakened} />
          {claims.contradicted > 0 && (
            <div className="mt-1 text-xs font-semibold text-red-600">
              ⚠ {claims.contradicted} contradicted
            </div>
          )}
        </SummaryCard>
        <SummaryCard title="Confidence">
          <div className="flex items-center gap-3 text-sm">
            <span className="text-emerald-600">↑ {confidence.increased}</span>
            <span className="text-orange-600">↓ {confidence.decreased}</span>
          </div>
        </SummaryCard>
        <SummaryCard title="Recommendation">
          <KindBadge kind={recommendation.kind} />
          {recommendation.old?.option && recommendation.new?.option &&
            recommendation.kind === "reversed" && (
              <div className="mt-1 text-xs text-slate-500">
                {recommendation.old.option} → {recommendation.new.option}
              </div>
            )}
        </SummaryCard>
      </div>

      {/* Claims (the substance) */}
      <section className="space-y-2">
        <h2 className="text-lg font-semibold text-slate-900">Claim changes</h2>
        {claims.items.filter((c) => c.kind !== "unchanged").length === 0 ? (
          <Card><p className="text-sm text-slate-500">No claim-level changes between these runs.</p></Card>
        ) : (
          claims.items
            .filter((c) => c.kind !== "unchanged")
            .map((c, i) => <ClaimDiffCard key={i} item={c} />)
        )}
      </section>

      {/* Sources */}
      <section className="space-y-2">
        <h2 className="text-lg font-semibold text-slate-900">Source changes</h2>
        {sources.items.filter((s) => s.kind !== "unchanged").length === 0 ? (
          <Card><p className="text-sm text-slate-500">No source changes.</p></Card>
        ) : (
          <Card className="space-y-2">
            {sources.items
              .filter((s) => s.kind !== "unchanged")
              .map((s, i) => (
                <div key={i} className="flex items-start justify-between gap-3 text-sm">
                  <span className="min-w-0 truncate text-slate-700">{s.title || s.url}</span>
                  <span className="flex shrink-0 items-center gap-2">
                    {s.changes.length > 0 && (
                      <span className="text-xs text-slate-400">{s.changes.join(", ")}</span>
                    )}
                    <KindBadge kind={s.kind} />
                  </span>
                </div>
              ))}
          </Card>
        )}
      </section>

      {/* Documents */}
      {documents.items.filter((d) => d.kind !== "unchanged").length > 0 && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold text-slate-900">Document changes</h2>
          <Card className="space-y-2">
            {documents.items
              .filter((d) => d.kind !== "unchanged")
              .map((d, i) => (
                <div key={i} className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-slate-700">📄 {d.filename}</span>
                  <span className="flex items-center gap-2">
                    {d.changes.length > 0 && (
                      <span className="text-xs text-slate-400">{d.changes.join(", ")}</span>
                    )}
                    <KindBadge kind={d.kind} />
                  </span>
                </div>
              ))}
          </Card>
        </section>
      )}
    </div>
  );
}

function SummaryCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3">
      <div className="mb-1 text-xs font-semibold uppercase text-slate-500">{title}</div>
      {children}
    </div>
  );
}

function Delta({ plus, minus, tilde }: { plus: number; minus: number; tilde: number }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-emerald-600">+{plus}</span>
      <span className="text-slate-400">−{minus}</span>
      {tilde > 0 && <span className="text-amber-600">~{tilde}</span>}
    </div>
  );
}

function ClaimDiffCard({ item }: { item: ClaimDiffItem }) {
  const [open, setOpen] = useState(false);
  const text = item.new_text ?? item.old_text ?? "";
  const hasEvidence = item.old_evidence.length > 0 || item.new_evidence.length > 0;

  return (
    <Card className="py-0">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-start justify-between gap-3 py-3 text-left"
      >
        <span className="flex items-start gap-2">
          {open ? (
            <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
          ) : (
            <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
          )}
          <span className="text-sm text-slate-800">{text}</span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {item.old_confidence != null && item.new_confidence != null && (
            <span className="text-xs font-semibold text-slate-500">
              {Math.round(item.old_confidence)} → {Math.round(item.new_confidence)}
            </span>
          )}
          <KindBadge kind={item.kind} />
        </span>
      </button>

      {item.reason && (
        <div className="pb-2 pl-6 text-xs text-slate-500">{item.reason}</div>
      )}

      {open && (
        <div className="border-t border-slate-100 py-3 pl-6 pr-2">
          {!hasEvidence ? (
            <p className="text-sm text-slate-400">No source-level evidence recorded.</p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              <EvidenceColumn
                title="Previous evidence"
                icon={<ArrowLeft className="h-3.5 w-3.5" />}
                items={item.old_evidence}
              />
              <EvidenceColumn
                title="Current evidence"
                icon={<ArrowRight className="h-3.5 w-3.5" />}
                items={item.new_evidence}
              />
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function EvidenceColumn({
  title,
  icon,
  items,
}: {
  title: string;
  icon: React.ReactNode;
  items: DiffEvidenceItem[];
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1 text-xs font-semibold uppercase text-slate-500">
        {icon} {title}
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-slate-400">None</p>
      ) : (
        <div className="space-y-2">
          {items.map((it, i) => (
            <div
              key={i}
              className={`rounded-lg border p-2.5 text-sm ${
                it.stance === "contradicts"
                  ? "border-orange-200 bg-orange-50/40"
                  : "border-slate-200"
              }`}
            >
              {it.passage && (
                <p className="mb-1.5 border-l-2 border-slate-300 pl-2 text-xs italic text-slate-600">
                  “{it.passage}”
                </p>
              )}
              {it.source_type === "documents" ? (
                <span className="text-xs font-medium text-sky-700">
                  📄 {it.title}
                  {it.page_number != null && (
                    <span className="text-slate-500"> · p.{it.page_number}</span>
                  )}
                </span>
              ) : (
                <a
                  href={it.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs font-medium text-brand-700 hover:underline"
                >
                  {it.title}
                </a>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
