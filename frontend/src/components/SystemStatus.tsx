import { useEffect, useState } from "react";
import { CheckCircle2, XCircle, AlertTriangle, Loader2 } from "lucide-react";
import { useHealth } from "../hooks/useHealth";
import { api } from "../api/client";
import type { Connectivity, HealthStatus } from "../api/types";
import { connectivityMeta } from "../lib/provenance";

type Tone = "ok" | "warn" | "bad";

const TONE_STYLES: Record<Tone, string> = {
  ok: "border-emerald-200 bg-emerald-50 text-emerald-700",
  warn: "border-amber-200 bg-amber-50 text-amber-700",
  bad: "border-red-200 bg-red-50 text-red-700",
};

function Pill({ tone, label }: { tone: Tone; label: string }) {
  const Icon = tone === "ok" ? CheckCircle2 : tone === "warn" ? AlertTriangle : XCircle;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${TONE_STYLES[tone]}`}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </span>
  );
}

/** Fixes shown when something isn't ready, so the user isn't left guessing. */
function hints(h: HealthStatus): string[] {
  const out: string[] = [];
  if (!h.llm.reachable) {
    out.push(
      `Ollama isn't reachable — start it and run \`ollama pull ${h.llm.model}\`.`
    );
  }
  if (!h.search.configured) {
    out.push(
      h.search.provider === "searxng"
        ? "SearXNG isn't reachable — start your SearXNG instance and set SEARXNG_URL."
        : "Tavily isn't configured — set TAVILY_API_KEY in backend/.env (or switch SEARCH_PROVIDER=searxng)."
    );
  }
  return out;
}

/** Live connectivity pill (#5): overall online/degraded/local/offline state. */
function ConnectivityPill() {
  const [conn, setConn] = useState<Connectivity | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = () =>
      api
        .connectivity()
        .then((c) => alive && setConn(c))
        .catch(() => alive && setConn(null));
    tick();
    const id = setInterval(tick, 30000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);
  if (!conn || !conn.enabled) return null;
  const m = connectivityMeta(conn.overall_status);
  return (
    <span
      title={`Connectivity: ${m.label}${conn.research_mode ? ` · ${conn.research_mode} research` : ""}`}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${m.className}`}
    >
      {m.dot} {m.label}
    </span>
  );
}

export default function SystemStatus({ compact = false }: { compact?: boolean }) {
  const { health, error, loading } = useHealth();

  if (loading && !health && !error) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" /> Checking system status…
      </div>
    );
  }

  if (error || !health) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
        <span className="font-medium">Backend unreachable.</span> Is the API running on
        port 8000? Start it with{" "}
        <code className="rounded bg-red-100 px-1">uvicorn app.main:app --port 8000</code>.
      </div>
    );
  }

  const llmTone: Tone = health.llm.reachable ? "ok" : "bad";
  const searchTone: Tone = health.search.configured ? "ok" : "warn";
  const embTone: Tone = health.knowledge.semantic ? "ok" : "warn";
  const fixes = hints(health);

  const pills = (
    <div className="flex flex-wrap items-center gap-2">
      <ConnectivityPill />
      <Pill
        tone={llmTone}
        label={
          health.llm.reachable
            ? `LLM · ${health.llm.model}`
            : "LLM · Ollama unreachable"
        }
      />
      <Pill
        tone={searchTone}
        label={
          health.search.configured
            ? `Search · ${health.search.provider}`
            : `Search · ${health.search.provider} not ready`
        }
      />
      <Pill
        tone={embTone}
        label={health.knowledge.semantic ? "Embeddings · on" : "Embeddings · keyword only"}
      />
    </div>
  );

  if (compact) return pills;

  const allReady = health.llm.reachable && health.search.configured;
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-medium text-slate-700">
          System status {allReady ? "— ready to run" : "— action needed before a run"}
        </span>
        {pills}
      </div>
      {fixes.length > 0 && (
        <ul className="space-y-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          {fixes.map((f, i) => (
            <li key={i}>• {f}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
