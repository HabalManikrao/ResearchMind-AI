// Research monitoring (#6) UI mapping — severity + health → label/colour/icon.
// Kept deterministic and self-contained, mirroring lib/provenance.ts.
import type { Severity, MonitorHealth } from "../api/types";

export interface SeverityMeta {
  label: string;
  icon: string;
  className: string; // pill styling (light/dark tolerant)
}

export const SEVERITY_META: Record<Severity, SeverityMeta> = {
  critical: {
    label: "Critical",
    icon: "⚠",
    className: "bg-red-100 text-red-700 border border-red-200",
  },
  high: {
    label: "High",
    icon: "⚠",
    className: "bg-orange-100 text-orange-700 border border-orange-200",
  },
  medium: {
    label: "Medium",
    icon: "•",
    className: "bg-amber-100 text-amber-700 border border-amber-200",
  },
  low: {
    label: "Low",
    icon: "·",
    className: "bg-slate-100 text-slate-600 border border-slate-200",
  },
};

export function severityMeta(severity: Severity | null | undefined): SeverityMeta {
  return (severity && SEVERITY_META[severity]) || SEVERITY_META.low;
}

export interface HealthMeta {
  label: string;
  className: string;
  dot: string; // dot colour class
}

export const HEALTH_META: Record<MonitorHealth, HealthMeta> = {
  healthy: { label: "Healthy", className: "text-emerald-700", dot: "bg-emerald-500" },
  degraded: { label: "Degraded", className: "text-amber-700", dot: "bg-amber-500" },
  offline: { label: "Offline", className: "text-slate-500", dot: "bg-slate-400" },
  failing: { label: "Failing", className: "text-red-700", dot: "bg-red-500" },
  disabled: { label: "Disabled", className: "text-slate-400", dot: "bg-slate-300" },
};

export function healthMeta(health: MonitorHealth | string | null | undefined): HealthMeta {
  return (health && HEALTH_META[health as MonitorHealth]) || HEALTH_META.offline;
}

// Human summary of a check's outcome for history rows.
export function checkStatusLabel(status: string): string {
  switch (status) {
    case "no_change":
      return "No meaningful change";
    case "changes":
      return "Changes detected";
    case "suppressed":
      return "Minor changes (suppressed)";
    case "degraded":
      return "Incomplete — will retry";
    case "failed":
      return "Check failed";
    default:
      return status;
  }
}

export const FREQUENCY_LABEL: Record<string, string> = {
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
};

export const NOTIFY_POLICY_LABEL: Record<string, string> = {
  all: "All meaningful changes",
  important: "Important changes only",
  critical: "Critical only",
};
