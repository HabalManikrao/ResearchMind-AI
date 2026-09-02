import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { ResearchMode, SourcePolicy } from "../api/types";
import { Card } from "../components/ui";
import SystemStatus from "../components/SystemStatus";

const MODES: { value: ResearchMode; label: string; desc: string }[] = [
  { value: "quick", label: "Quick", desc: "Few sources, fast, short report" },
  { value: "standard", label: "Standard", desc: "Multiple sources, detailed report" },
  { value: "deep", label: "Deep Research", desc: "Multi-agent, verification, gap loop" },
  { value: "technical_rd", label: "Technical R&D", desc: "Architecture & PoC focused" },
  { value: "comparison", label: "Comparison", desc: "Compare options side by side" },
  { value: "decision", label: "Decision", desc: "Recommend the best option" },
  { value: "market", label: "Market Intelligence", desc: "What's happening in the market right now" },
];

const SOURCES = [
  { id: "web", label: "Web", available: true },
  { id: "docs", label: "Official Docs", available: true },
  { id: "github", label: "GitHub", available: true },
  { id: "papers", label: "Research Papers", available: true },
  { id: "news", label: "News", available: true },
  { id: "community", label: "Community", available: true },
  { id: "documents", label: "My Documents", available: true },
];

export default function NewResearch() {
  const nav = useNavigate();
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<ResearchMode>("deep");
  const [sources, setSources] = useState<string[]>(["web", "docs", "github", "papers"]);
  const [policy, setPolicy] = useState<SourcePolicy>("live_preferred");
  const [constraints, setConstraints] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleSource = (id: string, available: boolean) => {
    if (!available) return;
    setSources((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  };

  // Market Intelligence relies on recent web + news, so ensure they're selected.
  useEffect(() => {
    if (mode === "market") {
      setSources((s) => Array.from(new Set([...s, "web", "news"])));
    }
  }, [mode]);

  const submit = async () => {
    if (query.trim().length < 3) {
      setError("Please describe what you want researched.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const proj = await api.createResearch({
        query: query.trim(),
        mode,
        sources_enabled: sources,
        source_policy: policy,
        constraints: constraints.trim() ? { notes: constraints.trim() } : {},
        auto_start: true,
      });
      nav(`/research/${proj.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create research");
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">New Research</h1>
        <p className="text-slate-500">
          Describe your goal — the agent will plan, research, verify, and report.
        </p>
      </div>

      <Card>
        <SystemStatus />
      </Card>

      <Card className="space-y-5">
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">
            What do you want me to research?
          </label>
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            rows={4}
            placeholder="e.g. Compare local vector databases for offline RAG on Windows — Python support, licensing, and performance. Recommend one."
            className="w-full rounded-lg border border-slate-300 p-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>

        <div>
          <label className="mb-2 block text-sm font-medium text-slate-700">Research Mode</label>
          {mode === "market" && (
            <p className="mb-2 rounded-lg bg-brand-50 px-3 py-2 text-xs text-brand-700">
              Market Intelligence biases search toward recent sources and produces a
              dated “current state” snapshot. Web + News are auto-selected.
            </p>
          )}
          <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
            {MODES.map((m) => (
              <button
                key={m.value}
                type="button"
                onClick={() => setMode(m.value)}
                className={`rounded-lg border p-3 text-left text-sm transition ${
                  mode === m.value
                    ? "border-brand-500 bg-brand-50 ring-1 ring-brand-500"
                    : "border-slate-200 hover:border-slate-300"
                }`}
              >
                <div className="font-medium text-slate-900">{m.label}</div>
                <div className="text-xs text-slate-500">{m.desc}</div>
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="mb-2 block text-sm font-medium text-slate-700">
            Research Sources
          </label>
          <div className="flex flex-wrap gap-2">
            {SOURCES.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => toggleSource(s.id, s.available)}
                disabled={!s.available}
                className={`rounded-full border px-3 py-1 text-sm transition ${
                  sources.includes(s.id)
                    ? "border-brand-500 bg-brand-50 text-brand-700"
                    : "border-slate-200 text-slate-600"
                } ${!s.available ? "cursor-not-allowed opacity-40" : ""}`}
                title={s.available ? "" : "Coming soon"}
              >
                {s.label}
                {!s.available && " · soon"}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">
            Source Policy
          </label>
          <select
            value={policy}
            onChange={(e) => setPolicy(e.target.value as SourcePolicy)}
            className="w-full rounded-lg border border-slate-300 p-2.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          >
            <option value="live_preferred">Live preferred — fall back to cache/local if offline</option>
            <option value="live_only">Live only — strict; never use cache (fail if unreachable)</option>
            <option value="cache_allowed">Cache allowed — reuse cached results freely</option>
            <option value="local_only">Local only — documents/memory only, no internet</option>
          </select>
          <p className="mt-1 text-xs text-slate-500">
            Controls how ResearchMind sources evidence when live providers are slow or
            unavailable. Cached and local evidence is always clearly labelled — never shown as live.
          </p>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">
            Additional Constraints <span className="text-slate-400">(optional)</span>
          </label>
          <input
            value={constraints}
            onChange={(e) => setConstraints(e.target.value)}
            placeholder="Offline only, open-source, Windows, Python…"
            className="w-full rounded-lg border border-slate-300 p-2.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <button
          onClick={submit}
          disabled={submitting}
          className="w-full rounded-lg bg-brand-600 px-4 py-2.5 font-medium text-white hover:bg-brand-700 disabled:opacity-60"
        >
          {submitting ? "Starting…" : "Start Research"}
        </button>
      </Card>
    </div>
  );
}
