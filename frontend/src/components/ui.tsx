import type { ClaimStatus, ProjectStatus, TaskStatus } from "../api/types";
import { evidenceStateMeta, freshnessMeta } from "../lib/evidence";

const STATUS_STYLES: Record<string, string> = {
  created: "bg-slate-100 text-slate-600",
  planning: "bg-amber-100 text-amber-700",
  running: "bg-blue-100 text-blue-700",
  paused: "bg-yellow-100 text-yellow-700",
  completed: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
  cancelled: "bg-slate-200 text-slate-600",
  // task
  pending: "bg-slate-100 text-slate-600",
  queued: "bg-slate-100 text-slate-600",
  retrying: "bg-amber-100 text-amber-700",
  // claim
  verified: "bg-emerald-100 text-emerald-700",
  partially_verified: "bg-lime-100 text-lime-700",
  conflicted: "bg-orange-100 text-orange-700",
  unverified: "bg-slate-100 text-slate-600",
  insufficient_evidence: "bg-slate-100 text-slate-500",
};

export function Badge({ status }: { status: ProjectStatus | TaskStatus | ClaimStatus }) {
  const cls = STATUS_STYLES[status] ?? "bg-slate-100 text-slate-600";
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

export function ProgressBar({ value }: { value: number }) {
  return (
    <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-200">
      <div
        className="h-full rounded-full bg-brand-500 transition-all duration-500"
        style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
      />
    </div>
  );
}

export function Card({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-xl border border-slate-200 bg-white p-5 shadow-sm ${className}`}>
      {children}
    </div>
  );
}

export function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <Card className="flex flex-col gap-1">
      <span className="text-2xl font-bold text-slate-900">{value}</span>
      <span className="text-sm text-slate-500">{label}</span>
    </Card>
  );
}

export function ReliabilityPill({ score }: { score: number }) {
  const color =
    score >= 85
      ? "bg-emerald-100 text-emerald-700"
      : score >= 65
      ? "bg-lime-100 text-lime-700"
      : score >= 45
      ? "bg-amber-100 text-amber-700"
      : "bg-red-100 text-red-700";
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${color}`}>{score}</span>
  );
}

/** Evidence-state chip for a claim: Supported / Weak / Conflicting / Outdated / Unverified. */
export function EvidenceStateBadge({ state }: { state: string }) {
  const m = evidenceStateMeta(state);
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${m.className}`}
    >
      {m.label}
    </span>
  );
}

/** Source freshness pill: 🟢 Fresh / 🟡 Aging / 🔴 Potentially outdated / ⚪ Unknown. */
export function FreshnessPill({ freshness }: { freshness: string }) {
  const m = freshnessMeta(freshness);
  return (
    <span
      title={m.label}
      className={`rounded px-1.5 py-0.5 text-xs font-medium ${m.className}`}
    >
      {m.dot} {m.label}
    </span>
  );
}
