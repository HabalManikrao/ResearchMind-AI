// Knowledge Graph (#7) UI helpers — labels for entity types, predicates, provenance.
// Deterministic and self-contained, mirroring lib/provenance.ts and lib/monitoring.ts.

export function entityTypeLabel(type: string): string {
  const t = (type || "other").toLowerCase();
  return t.charAt(0).toUpperCase() + t.slice(1);
}

const TYPE_CLASS: Record<string, string> = {
  technology: "bg-indigo-100 text-indigo-700",
  software: "bg-indigo-100 text-indigo-700",
  library: "bg-indigo-100 text-indigo-700",
  framework: "bg-indigo-100 text-indigo-700",
  product: "bg-sky-100 text-sky-700",
  company: "bg-emerald-100 text-emerald-700",
  organization: "bg-emerald-100 text-emerald-700",
  person: "bg-amber-100 text-amber-700",
  concept: "bg-violet-100 text-violet-700",
  location: "bg-teal-100 text-teal-700",
  event: "bg-rose-100 text-rose-700",
  project: "bg-slate-100 text-slate-700",
  document: "bg-slate-100 text-slate-700",
  other: "bg-slate-100 text-slate-600",
};

export function entityTypeClass(type: string): string {
  return TYPE_CLASS[(type || "other").toLowerCase()] || TYPE_CLASS.other;
}

// Human-readable predicate (e.g. "alternative_to" → "alternative to").
export function predicateLabel(predicate: string): string {
  return (predicate || "related_to").replace(/_/g, " ");
}

// Provenance of a graph fact (spec §18).
const PROVENANCE_META: Record<string, { label: string; title: string }> = {
  explicit: { label: "Explicit", title: "Present in existing structured data" },
  derived: { label: "Derived", title: "Deterministically derived from claims/evidence" },
  inferred: { label: "Inferred", title: "Inferred by a semantic/LLM process" },
};

export function provenanceKindMeta(kind: string) {
  return PROVENANCE_META[(kind || "derived").toLowerCase()] || PROVENANCE_META.derived;
}

// Relationship temporal status.
const STATUS_LABEL: Record<string, string> = {
  active: "Active",
  superseded: "Superseded",
  retracted: "Retracted",
  disputed: "Disputed",
  historical: "Historical",
};

export function relationshipStatusLabel(status: string): string {
  return STATUS_LABEL[(status || "active").toLowerCase()] || status;
}
