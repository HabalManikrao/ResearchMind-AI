import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Network, History, FileText, AlertTriangle } from "lucide-react";
import { api } from "../api/client";
import type { EntityClaim, EntityDetail as EntityDetailT } from "../api/types";
import { Card, EvidenceStateBadge } from "../components/ui";
import {
  entityTypeClass,
  entityTypeLabel,
  predicateLabel,
  provenanceKindMeta,
  relationshipStatusLabel,
} from "../lib/knowledgeGraph";

export default function EntityDetail() {
  const { id } = useParams<{ id: string }>();
  const [detail, setDetail] = useState<EntityDetailT | null>(null);
  const [current, setCurrent] = useState<EntityClaim[]>([]);
  const [historical, setHistorical] = useState<EntityClaim[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError(null);
    Promise.all([
      api.entity(id),
      api.entityClaims(id, "current"),
      api.entityClaims(id, "historical"),
    ])
      .then(([d, c, h]) => {
        setDetail(d);
        setCurrent(c);
        setHistorical(h);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load entity"))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <p className="text-slate-500">Loading…</p>;
  if (error)
    return (
      <Card>
        <p className="text-sm text-red-600">{error}</p>
        <Link to="/knowledge" className="mt-2 inline-block text-sm text-brand-600 hover:underline">
          ← Back to Knowledge
        </Link>
      </Card>
    );
  if (!detail) return null;

  const e = detail.entity;

  return (
    <div className="space-y-6">
      <Link to="/knowledge" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700">
        <ArrowLeft className="h-4 w-4" /> Knowledge
      </Link>

      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-bold text-slate-900">{e.canonical_name}</h1>
          <span className={`rounded px-2 py-0.5 text-xs font-medium ${entityTypeClass(e.entity_type)}`}>
            {entityTypeLabel(e.entity_type)}
          </span>
        </div>
        {e.description && <p className="mt-1 text-slate-600">{e.description}</p>}
        {e.aliases.length > 0 && (
          <p className="mt-1 text-sm text-slate-400">Also known as: {e.aliases.join(", ")}</p>
        )}
        <div className="mt-2 flex flex-wrap gap-4 text-xs text-slate-500">
          <span>{detail.current_claims} current claim(s)</span>
          <span>{detail.historical_claims} historical</span>
          <span>{detail.source_count} source(s)</span>
          <span>{detail.run_count} research run(s)</span>
          {e.last_observed_at && (
            <span>Last updated {new Date(e.last_observed_at).toLocaleDateString()}</span>
          )}
        </div>
      </div>

      {/* Related entities */}
      <section>
        <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-700">
          <Network className="h-4 w-4" /> Related entities
        </h2>
        {detail.related.length === 0 ? (
          <Card><p className="text-sm text-slate-500">No relationships recorded yet.</p></Card>
        ) : (
          <div className="space-y-2">
            {detail.related.map((r) => {
              const prov = provenanceKindMeta(r.provenance_kind);
              return (
                <Card key={r.relationship_id} className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <span className="text-sm text-slate-500">
                      {r.direction === "out" ? "" : "is "}
                      {predicateLabel(r.predicate)}
                      {r.direction === "out" ? " →" : " ←"}{" "}
                    </span>
                    <Link
                      to={`/knowledge/entities/${r.entity.id}`}
                      className="font-medium text-brand-700 hover:underline"
                    >
                      {r.entity.canonical_name}
                    </Link>
                  </div>
                  <div className="flex shrink-0 items-center gap-2 text-xs">
                    <span title={prov.title} className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-500">
                      {prov.label}
                    </span>
                    {r.status !== "active" && (
                      <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-700">
                        {relationshipStatusLabel(r.status)}
                      </span>
                    )}
                  </div>
                </Card>
              );
            })}
          </div>
        )}
      </section>

      {/* Current claims */}
      <ClaimSection
        title="Current knowledge"
        icon={<FileText className="h-4 w-4" />}
        claims={current}
        emptyText="No current claims about this entity."
      />

      {/* Historical claims */}
      {historical.length > 0 && (
        <ClaimSection
          title="Historical knowledge (superseded)"
          icon={<History className="h-4 w-4" />}
          claims={historical}
          muted
        />
      )}
    </div>
  );
}

function ClaimSection({
  title,
  icon,
  claims,
  emptyText,
  muted,
}: {
  title: string;
  icon: React.ReactNode;
  claims: EntityClaim[];
  emptyText?: string;
  muted?: boolean;
}) {
  return (
    <section>
      <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-700">
        {icon} {title}
      </h2>
      {claims.length === 0 ? (
        emptyText ? <Card><p className="text-sm text-slate-500">{emptyText}</p></Card> : null
      ) : (
        <div className="space-y-2">
          {claims.map((c) => (
            <Card key={c.claim_id} className={muted ? "opacity-70" : ""}>
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm text-slate-800">{c.text}</p>
                <div className="flex shrink-0 items-center gap-1.5">
                  {c.disputed && (
                    <span
                      title="Disputed — contradicting evidence exists"
                      className="inline-flex items-center gap-0.5 rounded bg-red-100 px-1.5 py-0.5 text-xs text-red-700"
                    >
                      <AlertTriangle className="h-3 w-3" /> Disputed
                    </span>
                  )}
                  <EvidenceStateBadge state={c.evidence_state} />
                </div>
              </div>
              <div className="mt-1 flex items-center gap-3 text-xs text-slate-400">
                <span>Confidence {Math.round(c.confidence)}%</span>
                <span>Run #{c.run_number}</span>
                <Link
                  to={`/research/${c.project_id}`}
                  className="text-brand-600 hover:underline"
                >
                  View evidence
                </Link>
              </div>
            </Card>
          ))}
        </div>
      )}
    </section>
  );
}
