import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Search, RefreshCw, Sparkles, Network } from "lucide-react";
import { api } from "../api/client";
import type {
  KnowledgeSearchResult,
  KnowledgeStatus,
  EntitySummary,
} from "../api/types";
import { Card } from "../components/ui";
import { entityTypeClass, entityTypeLabel } from "../lib/knowledgeGraph";

type Tab = "research" | "entities";

export default function Knowledge() {
  const [tab, setTab] = useState<Tab>("research");
  const [status, setStatus] = useState<KnowledgeStatus | null>(null);
  const [reindexing, setReindexing] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    api.knowledgeStatus().then(setStatus).catch(() => {});
  }, []);

  const reindex = async () => {
    setReindexing(true);
    setNote(null);
    try {
      const r = await api.reindexKnowledge();
      setNote(r.message);
    } catch (e) {
      setNote(e instanceof Error ? e.message : "Reindex failed");
    } finally {
      setReindexing(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Knowledge</h1>
          <p className="text-slate-500">
            Search prior research and explore the evidence-backed entity graph.
          </p>
        </div>
        {tab === "research" && (
          <button
            onClick={reindex}
            disabled={reindexing || !status?.enabled}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${reindexing ? "animate-spin" : ""}`} />
            Reindex
          </button>
        )}
      </div>

      <div className="flex gap-1 border-b border-slate-200">
        {(["research", "entities"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium capitalize ${
              tab === t
                ? "border-brand-500 text-brand-700"
                : "border-transparent text-slate-500 hover:text-slate-700"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "research" ? (
        <ResearchSearch status={status} note={note} />
      ) : (
        <EntitySearch />
      )}
    </div>
  );
}

function ResearchSearch({
  status,
  note,
}: {
  status: KnowledgeStatus | null;
  note: string | null;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<KnowledgeSearchResult[]>([]);
  const [searched, setSearched] = useState(false);
  const semantic = status?.semantic;

  const run = async () => {
    if (q.trim().length < 2) return;
    const r = await api.searchKnowledge(q.trim());
    setResults(r);
    setSearched(true);
  };

  return (
    <div className="space-y-4">
      {status && (
        <div
          className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
            semantic
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-amber-200 bg-amber-50 text-amber-800"
          }`}
        >
          <Sparkles className="h-4 w-4" />
          {semantic ? (
            <span>
              Semantic search active (embeddings via <code>{status.embedding_model}</code>).
            </span>
          ) : (
            <span>
              Semantic search unavailable — using keyword matching. Pull the embedding model
              (<code>ollama pull {status.embedding_model}</code>) to enable it.
            </span>
          )}
        </div>
      )}
      {note && <p className="text-sm text-slate-500">{note}</p>}

      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run()}
            placeholder="Search topics, objectives, prior findings…"
            className="w-full rounded-lg border border-slate-300 py-2 pl-9 pr-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
        <button
          onClick={run}
          className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          Search
        </button>
      </div>

      {searched && results.length === 0 && (
        <Card><p className="text-slate-500">No matching research found.</p></Card>
      )}
      <div className="space-y-2">
        {results.map((r) => (
          <Link key={r.project_id} to={`/research/${r.project_id}`}>
            <Card className="transition hover:border-brand-400">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="truncate font-medium text-slate-900">{r.title}</div>
                  <div className="truncate text-sm text-slate-500">{r.snippet}</div>
                </div>
                {r.score != null && (
                  <span className="shrink-0 rounded-full bg-brand-100 px-2 py-0.5 text-xs font-semibold text-brand-700">
                    {Math.round(r.score * 100)}% match
                  </span>
                )}
              </div>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}

export function EntitySearch() {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<EntitySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async (query: string) => {
    setLoading(true);
    setError(null);
    try {
      setItems(await api.entities({ q: query || undefined, limit: 50 }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load entities");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load(q.trim())}
            placeholder="Search entities by name or alias…"
            className="w-full rounded-lg border border-slate-300 py-2 pl-9 pr-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
        <button
          onClick={() => load(q.trim())}
          className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          Search
        </button>
      </div>

      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : error ? (
        <Card><p className="text-sm text-red-600">{error}</p></Card>
      ) : items.length === 0 ? (
        <Card>
          <div className="flex items-start gap-3">
            <Network className="mt-0.5 h-5 w-5 text-slate-400" />
            <p className="text-sm text-slate-500">
              No entities yet. Complete a research run and ResearchMind will extract entities
              (technologies, products, companies) into the knowledge graph.
            </p>
          </div>
        </Card>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {items.map((e) => (
            <Link key={e.id} to={`/knowledge/entities/${e.id}`}>
              <Card className="transition hover:border-brand-400">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate font-medium text-slate-900">
                      {e.canonical_name}
                    </div>
                    <span
                      className={`mt-1 inline-block rounded px-1.5 py-0.5 text-xs font-medium ${entityTypeClass(e.entity_type)}`}
                    >
                      {entityTypeLabel(e.entity_type)}
                    </span>
                  </div>
                  <span className="shrink-0 text-xs text-slate-400">
                    {e.mention_count} mention{e.mention_count === 1 ? "" : "s"}
                  </span>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
