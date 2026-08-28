// Pure presentation helpers for the evidence layer. Kept free of React so the
// mapping logic (evidence state + freshness -> label/style) is unit-testable.
import type { EvidenceState, Freshness } from "../api/types";

export const EVIDENCE_STATE_META: Record<
  EvidenceState,
  { label: string; className: string }
> = {
  supported: { label: "Supported", className: "bg-emerald-100 text-emerald-700" },
  weak: { label: "Weak evidence", className: "bg-amber-100 text-amber-700" },
  conflicting: {
    label: "Conflicting evidence",
    className: "bg-orange-100 text-orange-700",
  },
  outdated: { label: "Outdated evidence", className: "bg-rose-100 text-rose-700" },
  unverified: { label: "Unverified", className: "bg-slate-100 text-slate-600" },
};

export function evidenceStateMeta(state: string) {
  return EVIDENCE_STATE_META[state as EvidenceState] ?? EVIDENCE_STATE_META.unverified;
}

export const FRESHNESS_META: Record<
  Freshness,
  { label: string; dot: string; className: string }
> = {
  fresh: { label: "Fresh", dot: "🟢", className: "bg-emerald-100 text-emerald-700" },
  aging: { label: "Aging", dot: "🟡", className: "bg-amber-100 text-amber-700" },
  stale: {
    label: "Potentially outdated",
    dot: "🔴",
    className: "bg-rose-100 text-rose-700",
  },
  unknown: { label: "Unknown date", dot: "⚪", className: "bg-slate-100 text-slate-500" },
};

export function freshnessMeta(f: string) {
  return FRESHNESS_META[f as Freshness] ?? FRESHNESS_META.unknown;
}

/**
 * Derive the display state from a claim's raw status + confidence breakdown.
 * The backend already computes `evidence_state`; this is the fallback for older
 * data (and the single source of truth the unit tests pin the mapping against).
 */
export function deriveEvidenceState(
  status: string,
  meta?: { contradiction_count?: number; outdated?: boolean } | null,
): EvidenceState {
  if (status === "conflicted" || (meta?.contradiction_count ?? 0) > 0)
    return "conflicting";
  if (meta?.outdated) return "outdated";
  if (status === "verified") return "supported";
  if (status === "partially_verified") return "weak";
  return "unverified";
}
