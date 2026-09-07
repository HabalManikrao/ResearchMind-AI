import { useEffect, useState } from "react";
import { Plug, Globe, Cpu, Clock, Wrench } from "lucide-react";
import { api } from "../api/client";
import type { ApiVersion, CapabilityInfo } from "../api/types";
import { Card } from "../components/ui";

export default function Integrations() {
  const [caps, setCaps] = useState<CapabilityInfo[]>([]);
  const [version, setVersion] = useState<ApiVersion | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.capabilities(), api.apiVersion()])
      .then(([c, v]) => {
        setCaps(c.capabilities);
        setVersion(v);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  const groups = Array.from(new Set(caps.map((c) => c.group)));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
          <Plug className="h-6 w-6 text-brand-500" /> Integrations
        </h1>
        <p className="text-slate-500">
          Use ResearchMind programmatically via the REST API or autonomously via MCP. Both go
          through the same capability layer — identical evidence, provenance and security.
        </p>
      </div>

      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : error ? (
        <Card><p className="text-sm text-red-600">{error}</p></Card>
      ) : (
        <>
          {version && (
            <Card>
              <div className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
                <div><span className="text-slate-400">REST API</span>{" "}
                  <code className="text-slate-700">{version.interfaces.rest}</code></div>
                <div><span className="text-slate-400">API version</span>{" "}
                  <span className="text-slate-700">{version.api_version}</span></div>
                <div><span className="text-slate-400">MCP</span>{" "}
                  <span className="text-slate-700">{version.interfaces.mcp ? "enabled" : "off"}</span></div>
                <div><span className="text-slate-400">Capabilities</span>{" "}
                  <span className="text-slate-700">{version.capabilities}</span></div>
              </div>
            </Card>
          )}

          {groups.map((g) => (
            <section key={g}>
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
                {g}
              </h2>
              <div className="grid gap-2 sm:grid-cols-2">
                {caps.filter((c) => c.group === g).map((c) => (
                  <Card key={c.name}>
                    <div className="flex items-start justify-between gap-2">
                      <code className="text-sm font-medium text-slate-900">{c.name}</code>
                      <div className="flex shrink-0 gap-1 text-slate-400">
                        {c.requires_network && <Globe className="h-4 w-4" aria-label="requires network" />}
                        {c.may_invoke_llm && <Cpu className="h-4 w-4" aria-label="may invoke LLM" />}
                        {c.long_running && <Clock className="h-4 w-4" aria-label="long running" />}
                        {c.mutating && <Wrench className="h-4 w-4" aria-label="mutating" />}
                      </div>
                    </div>
                    <p className="mt-1 text-sm text-slate-500">{c.description}</p>
                  </Card>
                ))}
              </div>
            </section>
          ))}

          <section>
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              MCP client setup
            </h2>
            <Card>
              <p className="mb-2 text-sm text-slate-600">
                Add ResearchMind to an MCP-capable agent (stdio transport). Replace the
                placeholders — never commit a real token.
              </p>
              <pre className="overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
{`{
  "mcpServers": {
    "researchmind": {
      "command": "python",
      "args": ["-m", "app.mcp"],
      "cwd": "/path/to/ResearchMind/backend",
      "env": { "RESEARCHMIND_TOKEN": "<YOUR_API_TOKEN>" }
    }
  }
}`}
              </pre>
            </Card>
          </section>
        </>
      )}
    </div>
  );
}
