import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Search, RefreshCw, Sparkles } from "lucide-react";
import { api } from "../api/client";
import type { KnowledgeSearchResult, KnowledgeStatus } from "../api/types";
import { Card } from "../components/ui";

export default function Knowledge() {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<KnowledgeSearchResult[]>([]);
  const [searched, setSearched] = useState(false);
  const [status, setStatus] = useState<KnowledgeStatus | null>(null);
  const [reindexing, setReindexing] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    api.knowledgeStatus().then(setStatus).catch(() => {});
  }, []);

  const run = async () => {
    if (q.trim().length < 2) return;
    const r = await api.searchKnowledge(q.trim());
    setResults(r);
    setSearched(true);
  };

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

  const semantic = status?.semantic;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Knowledge Base</h1>
          <p className="text-slate-500">
            Search across previous research before starting something new (spec §14).
          </p>
        </div>
        <button
          onClick={reindex}
          disabled={reindexing || !status?.enabled}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${reindexing ? "animate-spin" : ""}`} />
          Reindex
        </button>
      </div>

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
              Semantic search unavailable — using keyword matching. Pull the embedding
              model (<code>ollama pull {status.embedding_model}</code>) to enable it.
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
