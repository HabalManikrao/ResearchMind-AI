import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Clock, Play, Trash2, Plus } from "lucide-react";
import { api } from "../api/client";
import type { ResearchMode, Schedule } from "../api/types";
import { Card } from "../components/ui";

const MODES: { value: ResearchMode; label: string }[] = [
  { value: "quick", label: "Quick" },
  { value: "standard", label: "Standard" },
  { value: "deep", label: "Deep Research" },
  { value: "technical_rd", label: "Technical R&D" },
  { value: "comparison", label: "Comparison" },
  { value: "decision", label: "Decision" },
  { value: "market", label: "Market Intelligence" },
];

const SOURCES = ["web", "docs", "github", "papers", "news", "community"];

const INTERVALS = [
  { label: "Every hour", minutes: 60 },
  { label: "Every 6 hours", minutes: 360 },
  { label: "Daily", minutes: 1440 },
  { label: "Weekly", minutes: 10080 },
];

function nextRunLabel(iso: string): string {
  const d = new Date(iso);
  return d.getTime() <= Date.now() ? "due now" : d.toLocaleString();
}

function cadenceLabel(s: Schedule): string {
  if (s.kind === "once") return "One-off";
  const m = s.interval_minutes ?? 0;
  const match = INTERVALS.find((i) => i.minutes === m);
  return match ? match.label : `Every ${m} min`;
}

export default function Scheduled() {
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<ResearchMode>("deep");
  const [sources, setSources] = useState<string[]>(["web", "docs", "github", "papers"]);
  const [intervalMinutes, setIntervalMinutes] = useState(1440);
  const [saving, setSaving] = useState(false);

  const load = () =>
    api.listSchedules().then(setSchedules).finally(() => setLoading(false));

  useEffect(() => {
    load();
  }, []);

  const toggleSource = (id: string) =>
    setSources((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  const create = async () => {
    if (query.trim().length < 3) {
      setError("Describe what to research on this schedule.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.createSchedule({
        query: query.trim(),
        mode,
        sources_enabled: sources,
        constraints: {},
        kind: "interval",
        interval_minutes: intervalMinutes,
      });
      setQuery("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create schedule");
    } finally {
      setSaving(false);
    }
  };

  const toggleEnabled = async (s: Schedule) => {
    await api.updateSchedule(s.id, { enabled: !s.enabled });
    await load();
  };
  const runNow = async (s: Schedule) => {
    await api.runScheduleNow(s.id);
    await load();
  };
  const remove = async (s: Schedule) => {
    if (!confirm(`Delete schedule “${s.title}”?`)) return;
    await api.deleteSchedule(s.id);
    await load();
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Scheduled Research</h1>
        <p className="text-slate-500">
          Run a research request automatically on a recurring cadence.
        </p>
      </div>

      <Card className="space-y-4">
        <div className="flex items-center gap-2 font-medium text-slate-800">
          <Plus className="h-4 w-4" /> New schedule
        </div>
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          rows={2}
          placeholder="e.g. Summarize this week's notable open-source LLM releases."
          className="w-full rounded-lg border border-slate-300 p-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
        <div className="flex flex-wrap gap-4">
          <label className="text-sm">
            <span className="mb-1 block font-medium text-slate-700">Mode</span>
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as ResearchMode)}
              className="rounded-lg border border-slate-300 p-2 text-sm"
            >
              {MODES.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium text-slate-700">Frequency</span>
            <select
              value={intervalMinutes}
              onChange={(e) => setIntervalMinutes(Number(e.target.value))}
              className="rounded-lg border border-slate-300 p-2 text-sm"
            >
              {INTERVALS.map((i) => (
                <option key={i.minutes} value={i.minutes}>
                  {i.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div>
          <span className="mb-1 block text-sm font-medium text-slate-700">Sources</span>
          <div className="flex flex-wrap gap-2">
            {SOURCES.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => toggleSource(s)}
                className={`rounded-full border px-3 py-1 text-sm transition ${
                  sources.includes(s)
                    ? "border-brand-500 bg-brand-50 text-brand-700"
                    : "border-slate-200 text-slate-600"
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          onClick={create}
          disabled={saving}
          className="rounded-lg bg-brand-600 px-4 py-2 font-medium text-white hover:bg-brand-700 disabled:opacity-60"
        >
          {saving ? "Saving…" : "Create schedule"}
        </button>
      </Card>

      {loading ? (
        <p className="text-slate-500">Loading…</p>
      ) : schedules.length === 0 ? (
        <Card>
          <p className="text-slate-500">No schedules yet.</p>
        </Card>
      ) : (
        <div className="space-y-2">
          {schedules.map((s) => (
            <Card key={s.id} className="flex items-center justify-between gap-4">
              <div className="min-w-0">
                <div className="truncate font-medium text-slate-900">{s.title}</div>
                <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                  <span className="inline-flex items-center gap-1">
                    <Clock className="h-3 w-3" /> {cadenceLabel(s)}
                  </span>
                  <span>· next: {nextRunLabel(s.next_run_at)}</span>
                  <span>· runs: {s.run_count}</span>
                  {s.last_project_id && (
                    <Link
                      to={`/research/${s.last_project_id}`}
                      className="text-brand-600 hover:underline"
                    >
                      · last run
                    </Link>
                  )}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-600">
                  <input
                    type="checkbox"
                    checked={s.enabled}
                    onChange={() => toggleEnabled(s)}
                  />
                  {s.enabled ? "On" : "Off"}
                </label>
                <button
                  onClick={() => runNow(s)}
                  title="Run now"
                  className="rounded-md border border-slate-200 p-1.5 text-slate-600 hover:bg-slate-50"
                >
                  <Play className="h-4 w-4" />
                </button>
                <button
                  onClick={() => remove(s)}
                  title="Delete"
                  className="rounded-md border border-slate-200 p-1.5 text-red-500 hover:bg-red-50"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
