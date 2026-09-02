// Pure presentation helpers for source provenance/availability (#5). Kept free of
// React so the mapping (provenance/availability -> label/badge) is unit-testable,
// mirroring lib/evidence.ts.
import type { Availability, Provenance, ResearchHealth } from "../api/types";

export const AVAILABILITY_META: Record<
  Availability,
  { label: string; dot: string; className: string }
> = {
  live: { label: "Live", dot: "🟢", className: "bg-emerald-100 text-emerald-700" },
  cached: { label: "Cached", dot: "🔵", className: "bg-sky-100 text-sky-700" },
  local: { label: "Local", dot: "📄", className: "bg-violet-100 text-violet-700" },
  stale: { label: "Stale", dot: "🟡", className: "bg-amber-100 text-amber-700" },
  unavailable: { label: "Unavailable", dot: "🔴", className: "bg-rose-100 text-rose-700" },
  unknown: { label: "Unknown", dot: "⚪", className: "bg-slate-100 text-slate-500" },
};

export function availabilityMeta(a: string) {
  return AVAILABILITY_META[a as Availability] ?? AVAILABILITY_META.unknown;
}

const PROVENANCE_TO_AVAILABILITY: Record<Provenance, Availability> = {
  live_web: "live",
  cached_web: "cached",
  local_document: "local",
  local_memory: "local",
  local_database: "local",
};

/**
 * Derive the display availability from provenance + freshness. Mirrors the backend
 * `availability_of` — freshness "stale" wins, otherwise provenance maps through. Used
 * as a fallback when the backend `availability` field isn't present.
 */
export function deriveAvailability(provenance: string, freshness: string): Availability {
  if (freshness === "stale") return "stale";
  return PROVENANCE_TO_AVAILABILITY[provenance as Provenance] ?? "unknown";
}

export const RESEARCH_HEALTH_META: Record<
  ResearchHealth,
  { label: string; dot: string; className: string }
> = {
  fully_live: { label: "Fully live", dot: "🟢", className: "bg-emerald-100 text-emerald-700" },
  partially_degraded: {
    label: "Partially degraded",
    dot: "🟡",
    className: "bg-amber-100 text-amber-700",
  },
  cache_assisted: { label: "Cache-assisted", dot: "🔵", className: "bg-sky-100 text-sky-700" },
  local_only: { label: "Local only", dot: "📄", className: "bg-violet-100 text-violet-700" },
  external_unavailable: {
    label: "External sources unavailable",
    dot: "🔴",
    className: "bg-rose-100 text-rose-700",
  },
};

export function researchHealthMeta(h: string) {
  return (
    RESEARCH_HEALTH_META[h as ResearchHealth] ?? {
      label: h || "Unknown",
      dot: "⚪",
      className: "bg-slate-100 text-slate-500",
    }
  );
}

export const CONNECTIVITY_META: Record<
  string,
  { label: string; dot: string; className: string }
> = {
  online: { label: "Online", dot: "🟢", className: "border-emerald-200 bg-emerald-50 text-emerald-700" },
  recovering: { label: "Recovering", dot: "🟢", className: "border-emerald-200 bg-emerald-50 text-emerald-700" },
  degraded: { label: "Degraded", dot: "🟡", className: "border-amber-200 bg-amber-50 text-amber-700" },
  local_only: { label: "Local only", dot: "📄", className: "border-violet-200 bg-violet-50 text-violet-700" },
  offline: { label: "Offline", dot: "🔴", className: "border-rose-200 bg-rose-50 text-rose-700" },
  unknown: { label: "Unknown", dot: "⚪", className: "border-slate-200 bg-slate-50 text-slate-500" },
};

export function connectivityMeta(state: string) {
  return CONNECTIVITY_META[state] ?? CONNECTIVITY_META.unknown;
}
