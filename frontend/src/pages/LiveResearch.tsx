import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Pause,
  Play,
  Square,
  Activity,
  Download,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  GitCompare,
  Radar,
} from "lucide-react";
import { api } from "../api/client";
import type {
  Claim,
  ClaimEvidenceItem,
  Conflict,
  KnowledgeGap,
  ProjectDetail,
  Question,
  Recommendation,
  Report,
  RunSummary,
  Solution,
  Source,
} from "../api/types";
import { useEventStream } from "../hooks/useEventStream";
import {
  Badge,
  Card,
  EvidenceStateBadge,
  FreshnessPill,
  ProgressBar,
  ProvenancePill,
  ReliabilityPill,
} from "../components/ui";
import KnowledgeGraphView from "../components/KnowledgeGraphView";
import DocumentsPanel from "../components/DocumentsPanel";
import BriefPanel from "../components/BriefPanel";
import type {
  KnowledgeGraph,
  SourceHealth,
  MonitorDetail,
  MonitorCheck,
  MonitorFrequency,
  NotifyPolicy,
} from "../api/types";
import { researchHealthMeta } from "../lib/provenance";
import {
  severityMeta,
  healthMeta,
  checkStatusLabel,
  FREQUENCY_LABEL,
  NOTIFY_POLICY_LABEL,
} from "../lib/monitoring";

type Tab =
  | "activity"
  | "brief"
  | "plan"
  | "sources"
  | "documents"
  | "claims"
  | "conflicts"
  | "recommendation"
  | "graph"
  | "report"
  | "monitoring";

const ACTIVE = ["running", "planning", "paused"];

export default function LiveResearch() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [tab, setTab] = useState<Tab>("activity");
  const [questions, setQuestions] = useState<Question[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [gaps, setGaps] = useState<KnowledgeGap[]>([]);
  const [solutions, setSolutions] = useState<Solution[]>([]);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [graph, setGraph] = useState<KnowledgeGraph | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [retryErr, setRetryErr] = useState<string | null>(null);

  const isActive = project ? ACTIVE.includes(project.status) : false;
  const { events, progress, stage, finished } = useEventStream(id, isActive);

  const loadProject = useCallback(async () => {
    if (!id) return;
    const p = await api.getResearch(id);
    setProject(p);
    return p;
  }, [id]);

  // The subset that actually changes while a run is in progress — polled live. Uses
  // allSettled so a single rate-limited/failed endpoint never blanks the whole tab, and keeps
  // the per-tick request count low so normal polling stays under the backend rate limit.
  const loadLive = useCallback(async () => {
    if (!id) return;
    const [q, s, c, cf, g] = await Promise.allSettled([
      api.questions(id), api.sources(id), api.claims(id), api.conflicts(id), api.gaps(id),
    ]);
    if (q.status === "fulfilled") setQuestions(q.value);
    if (s.status === "fulfilled") setSources(s.value);
    if (c.status === "fulfilled") setClaims(c.value);
    if (cf.status === "fulfilled") setConflicts(cf.value);
    if (g.status === "fulfilled") setGaps(g.value);
  }, [id]);

  // Full load — live subset + completion-only artifacts (report/solutions/recommendation/
  // graph/lineage). These only exist at/after completion, so they're loaded on the initial
  // load and the final refresh, NOT on every active-run tick (avoids redundant polling).
  const loadData = useCallback(async () => {
    if (!id) return;
    await loadLive();
    const [sol, rec, r, graph, runs] = await Promise.allSettled([
      api.solutions(id), api.recommendation(id), api.report(id),
      api.knowledgeGraph(id), api.runs(id),
    ]);
    if (sol.status === "fulfilled") setSolutions(sol.value);
    if (rec.status === "fulfilled") setRecommendation(rec.value);
    if (r.status === "fulfilled") setReport(r.value);
    if (graph.status === "fulfilled") setGraph(graph.value);
    if (runs.status === "fulfilled") setRuns(runs.value);
  }, [id, loadLive]);

  // Initial load.
  useEffect(() => {
    loadProject().then((p) => {
      if (p && p.status === "completed") setTab("report");
    });
    loadData();
  }, [loadProject, loadData]);

  // While active, refresh only detail + the live subset so plan/sources/claims populate live
  // without hammering the completion-only endpoints (keeps polling under the backend rate limit).
  useEffect(() => {
    if (!isActive) return;
    const t = setInterval(() => {
      loadProject();
      loadLive();
    }, 4000);
    return () => clearInterval(t);
  }, [isActive, loadProject, loadLive]);

  // When the stream reports completion, do a final refresh and jump to the report.
  useEffect(() => {
    if (finished) {
      loadProject();
      loadData().then(() => setTab("report"));
    }
  }, [finished, loadProject, loadData]);

  const control = async (action: "pause" | "resume" | "stop") => {
    if (!id) return;
    await api[action](id);
    await loadProject();
  };

  // Retry a FAILED run in place. The backend resets transient state and restarts the
  // same project (returning it as PLANNING), so setting it here flips isActive → true
  // and the existing polling + SSE resume automatically. Guarded so a double-click can't
  // fire two retries.
  const retry = async () => {
    if (!id || retrying) return;
    setRetrying(true);
    setRetryErr(null);
    try {
      const restarted = await api.retry(id);
      setProject(restarted);
      setTab("activity");
    } catch (e) {
      setRetryErr(e instanceof Error ? e.message : "Retry failed");
    } finally {
      setRetrying(false);
    }
  };

  if (!project) return <p className="text-slate-500">Loading…</p>;

  const displayProgress = isActive ? Math.max(progress, project.progress) : project.progress;

  const TABS: { key: Tab; label: string; count?: number }[] = [
    { key: "activity", label: "Activity" },
    { key: "brief", label: "Brief" },
    { key: "plan", label: "Plan", count: questions.length },
    { key: "sources", label: "Sources", count: sources.length },
    { key: "documents", label: "Documents" },
    { key: "claims", label: "Claims", count: claims.length },
    { key: "conflicts", label: "Conflicts", count: conflicts.length },
    { key: "recommendation", label: "Recommendation" },
    { key: "graph", label: "Graph" },
    { key: "report", label: "Report" },
    { key: "monitoring", label: "Monitoring" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-bold text-slate-900">{project.title}</h1>
          <p className="mt-1 text-slate-500">{project.objective ?? project.query}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Badge status={project.status} />
          {project.status === "running" && (
            <>
              <IconBtn onClick={() => control("pause")} title="Pause">
                <Pause className="h-4 w-4" />
              </IconBtn>
              <IconBtn onClick={() => control("stop")} title="Stop">
                <Square className="h-4 w-4" />
              </IconBtn>
            </>
          )}
          {project.status === "paused" && (
            <IconBtn onClick={() => control("resume")} title="Resume">
              <Play className="h-4 w-4" />
            </IconBtn>
          )}
        </div>
      </div>

      <Card>
        <div className="mb-2 flex items-center justify-between text-sm">
          <span className="font-medium text-slate-700">{stage || project.current_stage || "…"}</span>
          <span className="text-slate-500">{displayProgress}%</span>
        </div>
        <ProgressBar value={displayProgress} />
        {project.error && <p className="mt-3 text-sm text-red-600">Error: {project.error}</p>}
      </Card>

      <FailedResearchCard
        status={project.status}
        error={project.error}
        retrying={retrying}
        retryErr={retryErr}
        onRetry={retry}
      />

      <LineageBar
        project={project}
        runs={runs}
        onAgain={async (intent) => {
          const child = await api.researchAgain(project.id, { intent });
          navigate(`/research/${child.id}`);
        }}
      />

      <ResearchHealthBanner health={project.report_meta?.source_health} />

      <div className="flex gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-medium transition ${
              tab === t.key
                ? "border-b-2 border-brand-600 text-brand-700"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {t.label}
            {t.count !== undefined && t.count > 0 && (
              <span className="ml-1.5 rounded-full bg-slate-100 px-1.5 text-xs text-slate-600">
                {t.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {tab === "activity" && <ActivityTab events={events} project={project} />}
      {tab === "brief" && <BriefPanel projectId={id!} />}
      {tab === "plan" && <PlanTab questions={questions} gaps={gaps} />}
      {tab === "sources" && <SourcesTab sources={sources} />}
      {tab === "documents" && <DocumentsPanel projectId={id!} />}
      {tab === "claims" && <ClaimsTab claims={claims} projectId={id!} />}
      {tab === "conflicts" && <ConflictsTab conflicts={conflicts} />}
      {tab === "recommendation" && (
        <RecommendationTab
          recommendation={recommendation}
          solutions={solutions}
          isActive={isActive}
        />
      )}
      {tab === "graph" && <GraphTab graph={graph} />}
      {tab === "report" && <ReportTab report={report} isActive={isActive} />}
      {tab === "monitoring" && (
        <MonitoringTab projectId={id!} completed={project.status === "completed"} />
      )}
    </div>
  );
}

const INTENTS: { value: "refresh" | "deepen" | "verify" | "full"; label: string; hint: string }[] = [
  { value: "refresh", label: "Refresh", hint: "Re-check whether prior findings still hold; prefer newer info" },
  { value: "deepen", label: "Deepen", hint: "Focus on the open / unresolved questions" },
  { value: "verify", label: "Verify", hint: "Re-check the important prior claims" },
  { value: "full", label: "Full re-research", hint: "Fresh comprehensive run, prior run kept as context" },
];

export function LineageBar({
  project,
  runs,
  onAgain,
}: {
  project: ProjectDetail;
  runs: RunSummary[];
  onAgain: (intent: "refresh" | "deepen" | "verify" | "full") => Promise<void>;
}) {
  const [intent, setIntent] = useState<"refresh" | "deepen" | "verify" | "full">("refresh");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Only meaningful once a run is completed (you continue a finished snapshot) or
  // when this project is part of a multi-run lineage.
  const completed = project.status === "completed";
  if (!completed && runs.length <= 1) return null;

  const total = runs.length || 1;
  const current = project.run_number || 1;
  const previous = runs
    .filter((r) => r.run_number < current)
    .sort((a, b) => b.run_number - a.run_number)[0];

  const doAgain = async () => {
    setBusy(true);
    setErr(null);
    try {
      await onAgain(intent);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to start a new run");
      setBusy(false);
    }
  };

  return (
    <Card className="flex flex-wrap items-center justify-between gap-3 border-slate-200 bg-slate-50/60 py-3">
      <div className="flex items-center gap-2 text-sm text-slate-600">
        <span className="rounded-full bg-white px-2 py-0.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200">
          Run #{current}{total > 1 ? ` of ${total}` : ""}
        </span>
        {project.run_intent && project.run_intent !== "original" && (
          <span className="text-xs uppercase tracking-wide text-slate-400">
            {project.run_intent}
          </span>
        )}
        {previous && (
          <Link
            to={`/research/${project.id}/diff/${previous.id}`}
            className="inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:underline"
          >
            <GitCompare className="h-3.5 w-3.5" /> Compare with Run #{previous.run_number}
          </Link>
        )}
      </div>

      {completed && (
        <div className="flex items-center gap-2">
          {err && <span className="text-xs text-red-600">{err}</span>}
          <select
            value={intent}
            onChange={(e) => setIntent(e.target.value as typeof intent)}
            title={INTENTS.find((i) => i.value === intent)?.hint}
            className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-700 focus:border-brand-500 focus:outline-none"
          >
            {INTENTS.map((i) => (
              <option key={i.value} value={i.value}>{i.label}</option>
            ))}
          </select>
          <button
            onClick={doAgain}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
          >
            <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />
            {busy ? "Starting…" : "Research Again"}
          </button>
        </div>
      )}
    </Card>
  );
}

function IconBtn({
  children,
  onClick,
  title,
}: {
  children: React.ReactNode;
  onClick: () => void;
  title: string;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className="rounded-lg border border-slate-300 p-2 text-slate-600 hover:bg-slate-100"
    >
      {children}
    </button>
  );
}

function ActivityTab({
  events,
  project,
}: {
  events: { type: string; message: string; timestamp: string }[];
  project: ProjectDetail;
}) {
  const historical = !ACTIVE.includes(project.status) && events.length === 0;
  return (
    <Card>
      {historical ? (
        <p className="text-sm text-slate-500">
          This run has finished — live activity is only streamed while research is in progress.
          See the Report, Sources, and Claims tabs for results.
        </p>
      ) : events.length === 0 ? (
        <p className="flex items-center gap-2 text-sm text-slate-500">
          <Activity className="h-4 w-4 animate-pulse" /> Waiting for agent activity…
        </p>
      ) : (
        <ul className="space-y-2">
          {[...events].reverse().map((e, i) => (
            <li key={i} className="flex items-start gap-3 text-sm">
              <span
                className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
                  e.type === "error"
                    ? "bg-red-500"
                    : e.type === "done"
                    ? "bg-emerald-500"
                    : e.type === "activity"
                    ? "bg-brand-500"
                    : "bg-slate-300"
                }`}
              />
              <div>
                <span className="text-slate-700">{e.message}</span>
                <span className="ml-2 text-xs text-slate-400">
                  {new Date(e.timestamp).toLocaleTimeString()}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function PlanTab({ questions, gaps }: { questions: Question[]; gaps: KnowledgeGap[] }) {
  if (questions.length === 0)
    return <Card><p className="text-sm text-slate-500">No questions yet.</p></Card>;
  return (
    <div className="space-y-4">
      {gaps.length > 0 && (
        <Card className="border-amber-200 bg-amber-50/50">
          <div className="mb-2 text-sm font-semibold text-amber-800">
            Knowledge gaps detected ({gaps.length}) — triggered automatic follow-up research
          </div>
          <ul className="space-y-1.5">
            {gaps.map((g) => (
              <li key={g.id} className="text-sm text-slate-700">
                <span className="font-medium">{g.question}</span>
                {g.reason && <span className="text-slate-500"> — {g.reason}</span>}
              </li>
            ))}
          </ul>
        </Card>
      )}
      <div className="space-y-2">
      {questions.map((q) => (
        <Card key={q.id} className="flex items-center justify-between gap-3 py-3">
          <div>
            <span className="text-sm text-slate-800">{q.text}</span>
            {q.is_followup && (
              <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-700">
                follow-up
              </span>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2 text-xs text-slate-500">
            <span>P{q.priority}</span>
            {q.answered && (
              <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-emerald-700">answered</span>
            )}
          </div>
        </Card>
      ))}
      </div>
    </div>
  );
}

const SOURCE_TYPE_STYLE: Record<string, string> = {
  web: "bg-slate-100 text-slate-600",
  docs: "bg-indigo-100 text-indigo-700",
  github: "bg-purple-100 text-purple-700",
  papers: "bg-teal-100 text-teal-700",
  news: "bg-rose-100 text-rose-700",
  community: "bg-amber-100 text-amber-700",
  documents: "bg-sky-100 text-sky-700",
};

function SourceTypeBadge({ type }: { type: string }) {
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-xs font-medium uppercase ${
        SOURCE_TYPE_STYLE[type] ?? "bg-slate-100 text-slate-600"
      }`}
    >
      {type}
    </span>
  );
}

function SourceMeta({ source }: { source: Source }) {
  const m = source.meta ?? {};
  const bits: string[] = [];
  if (source.source_type === "github") {
    if (m.stars != null) bits.push(`★ ${m.stars}`);
    if (m.language) bits.push(String(m.language));
    if (m.license) bits.push(String(m.license));
    if (m.status) bits.push(String(m.status));
  } else if (source.source_type === "papers") {
    const authors = (m.authors as string[]) ?? [];
    if (authors.length) bits.push(authors.slice(0, 3).join(", ") + (authors.length > 3 ? " et al." : ""));
    if (m.venue) bits.push(String(m.venue));
  }
  if (source.published_date) bits.push(source.published_date);
  if (bits.length === 0) return null;
  return <div className="mt-1 text-xs text-slate-500">{bits.join(" · ")}</div>;
}

/**
 * Research Health banner (#5): shows the run's live/cached/local/unavailable source
 * mix. Rendered only when there's something worth disclosing — a fully-live run stays
 * quiet so the UI doesn't nag (spec §15, §22, §38).
 */
export function ResearchHealthBanner({ health }: { health?: SourceHealth | null }) {
  if (!health) return null;
  const quiet =
    health.research_health === "fully_live" && !health.unavailable && !health.cached;
  if (quiet) return null;

  const m = researchHealthMeta(health.research_health);
  const counts: [string, number][] = [
    ["Live", health.live],
    ["Cached", health.cached],
    ["Local", health.local],
    ["Stale", health.stale],
    ["Unavailable", health.unavailable],
  ];
  return (
    <div className={`rounded-lg border px-3 py-2 text-sm ${m.className}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium">
          {m.dot} Research Health — {m.label}
        </span>
        <span className="flex flex-wrap gap-x-3 text-xs opacity-90">
          {counts
            .filter(([, n]) => n > 0)
            .map(([label, n]) => (
              <span key={label}>
                {label}: {n}
              </span>
            ))}
        </span>
      </div>
      {health.research_mode === "local" && (
        <p className="mt-1 text-xs opacity-90">
          Performed using local/cached sources; live web verification was unavailable.
        </p>
      )}
      {health.unavailable > 0 && (
        <p className="mt-1 text-xs opacity-90">
          Some external sources could not be reached — coverage is incomplete.
        </p>
      )}
    </div>
  );
}

function SourcesTab({ sources }: { sources: Source[] }) {
  const [filter, setFilter] = useState<string>("all");
  if (sources.length === 0)
    return <Card><p className="text-sm text-slate-500">No sources collected yet.</p></Card>;

  const types = Array.from(new Set(sources.map((s) => s.source_type)));
  const shown = filter === "all" ? sources : sources.filter((s) => s.source_type === filter);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <FilterChip label={`All (${sources.length})`} active={filter === "all"} onClick={() => setFilter("all")} />
        {types.map((t) => (
          <FilterChip
            key={t}
            label={`${t} (${sources.filter((s) => s.source_type === t).length})`}
            active={filter === t}
            onClick={() => setFilter(t)}
          />
        ))}
      </div>
      {shown.map((s) => (
        <Card key={s.id} className="py-3">
          <div className="flex items-start justify-between gap-3">
            <a
              href={s.url}
              target="_blank"
              rel="noreferrer"
              className="font-medium text-brand-700 hover:underline"
            >
              {s.title}
            </a>
            <div className="flex shrink-0 items-center gap-2">
              <SourceTypeBadge type={s.source_type} />
              <ReliabilityPill score={s.reliability_score} />
            </div>
          </div>
          {s.summary && <p className="mt-1 text-sm text-slate-600">{s.summary}</p>}
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <ProvenancePill availability={s.availability} />
            <FreshnessPill freshness={s.freshness} />
            <SourceMeta source={s} />
          </div>
          <div className="mt-1 truncate text-xs text-slate-400">{s.url}</div>
        </Card>
      ))}
    </div>
  );
}

function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full border px-3 py-1 text-xs font-medium capitalize transition ${
        active
          ? "border-brand-500 bg-brand-50 text-brand-700"
          : "border-slate-200 text-slate-600 hover:border-slate-300"
      }`}
    >
      {label}
    </button>
  );
}

export function ClaimsTab({ claims, projectId }: { claims: Claim[]; projectId: string }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<Record<string, ClaimEvidenceItem[]>>({});
  const [loading, setLoading] = useState<string | null>(null);

  const toggle = async (claim: Claim) => {
    if (openId === claim.id) {
      setOpenId(null);
      return;
    }
    setOpenId(claim.id);
    if (evidence[claim.id] === undefined) {
      setLoading(claim.id);
      try {
        const res = await api.claimEvidence(projectId, claim.id);
        setEvidence((e) => ({ ...e, [claim.id]: res.evidence }));
      } catch {
        setEvidence((e) => ({ ...e, [claim.id]: [] }));
      } finally {
        setLoading(null);
      }
    }
  };

  if (claims.length === 0)
    return <Card><p className="text-sm text-slate-500">No claims verified yet.</p></Card>;

  return (
    <div className="space-y-2">
      {claims.map((c) => {
        const open = openId === c.id;
        const meta = c.confidence_meta;
        return (
          <Card key={c.id} className="py-0">
            <button
              onClick={() => toggle(c)}
              className="flex w-full items-start justify-between gap-3 py-3 text-left"
            >
              <span className="flex items-start gap-2">
                {open ? (
                  <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
                ) : (
                  <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
                )}
                <span className="text-sm text-slate-800">{c.text}</span>
              </span>
              <span className="flex shrink-0 items-center gap-2">
                <EvidenceStateBadge state={c.evidence_state} />
                <span className="text-xs font-semibold text-slate-500">
                  {c.confidence}%
                </span>
              </span>
            </button>
            <div className="flex flex-wrap gap-x-3 gap-y-1 pb-2 pl-6 text-xs text-slate-400">
              <span>{meta?.support_count ?? c.supporting_source_ids.length} supporting</span>
              {(meta?.contradiction_count ?? 0) > 0 && (
                <span className="text-orange-600">
                  {meta?.contradiction_count} contradicting
                </span>
              )}
            </div>

            {open && (
              <div className="border-t border-slate-100 py-3 pl-6 pr-2">
                {meta?.reasons && meta.reasons.length > 0 && (
                  <div className="mb-3">
                    <div className="mb-1 text-xs font-semibold uppercase text-slate-500">
                      Why this confidence
                    </div>
                    <ul className="list-disc space-y-0.5 pl-5 text-sm text-slate-600">
                      {meta.reasons.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {loading === c.id ? (
                  <p className="text-sm text-slate-400">Loading evidence…</p>
                ) : (
                  <EvidenceList items={evidence[c.id] ?? []} />
                )}
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}

function EvidenceList({ items }: { items: ClaimEvidenceItem[] }) {
  if (items.length === 0)
    return <p className="text-sm text-slate-400">No source-level evidence recorded.</p>;
  const supporting = items.filter((i) => i.stance === "supports");
  const contradicting = items.filter((i) => i.stance === "contradicts");
  return (
    <div className="space-y-4">
      {supporting.length > 0 && (
        <EvidenceGroup title={`Supporting evidence (${supporting.length})`} items={supporting} />
      )}
      {contradicting.length > 0 && (
        <EvidenceGroup
          title={`Contradicting evidence (${contradicting.length})`}
          items={contradicting}
          contradicting
        />
      )}
    </div>
  );
}

function EvidenceGroup({
  title,
  items,
  contradicting = false,
}: {
  title: string;
  items: ClaimEvidenceItem[];
  contradicting?: boolean;
}) {
  return (
    <div>
      <div
        className={`mb-1.5 text-xs font-semibold uppercase ${
          contradicting ? "text-orange-600" : "text-emerald-700"
        }`}
      >
        {title}
      </div>
      <div className="space-y-2">
        {items.map((it) => (
          <div
            key={it.source_id}
            className={`rounded-lg border p-3 ${
              contradicting ? "border-orange-200 bg-orange-50/40" : "border-slate-200"
            }`}
          >
            {it.passage && (
              <p className="mb-2 border-l-2 border-slate-300 pl-2 text-sm italic text-slate-600">
                “{it.passage}”
              </p>
            )}
            <div className="flex items-start justify-between gap-3">
              {it.source_type === "documents" ? (
                <span className="text-sm font-medium text-sky-700">
                  📄 {it.title}
                  {it.page_number != null && (
                    <span className="text-slate-500"> · p.{it.page_number}</span>
                  )}
                </span>
              ) : (
                <a
                  href={it.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm font-medium text-brand-700 hover:underline"
                >
                  {it.title}
                </a>
              )}
              <div className="flex shrink-0 items-center gap-1.5">
                <SourceTypeBadge type={it.source_type} />
                <ReliabilityPill score={it.reliability_score} />
              </div>
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <ProvenancePill availability={it.availability} />
              <FreshnessPill freshness={it.freshness} />
              {it.published_date && (
                <span className="text-xs text-slate-400">{it.published_date}</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const SEVERITY_STYLE: Record<string, string> = {
  high: "bg-red-100 text-red-700",
  medium: "bg-orange-100 text-orange-700",
  low: "bg-yellow-100 text-yellow-700",
};

function ConflictsTab({ conflicts }: { conflicts: Conflict[] }) {
  if (conflicts.length === 0)
    return (
      <Card>
        <p className="text-sm text-slate-500">
          No contradictions were detected across sources.
        </p>
      </Card>
    );
  return (
    <div className="space-y-3">
      {conflicts.map((c) => (
        <Card key={c.id} className="border-orange-200">
          <div className="mb-2 flex items-center gap-2">
            <span
              className={`rounded px-1.5 py-0.5 text-xs font-semibold uppercase ${
                SEVERITY_STYLE[c.severity] ?? "bg-slate-100 text-slate-600"
              }`}
            >
              {c.severity}
            </span>
            <span className="text-xs text-slate-500">{c.status.replace(/_/g, " ")}</span>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
              {c.statement_a}
            </div>
            <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
              {c.statement_b}
            </div>
          </div>
          {c.explanation && (
            <p className="mt-2 text-sm text-slate-500">{c.explanation}</p>
          )}
        </Card>
      ))}
    </div>
  );
}

function RecommendationTab({
  recommendation,
  solutions,
  isActive,
}: {
  recommendation: Recommendation | null;
  solutions: Solution[];
  isActive: boolean;
}) {
  if (!recommendation && solutions.length === 0)
    return (
      <Card>
        <p className="text-sm text-slate-500">
          {isActive
            ? "The recommendation and solution comparison appear once R&D analysis runs."
            : "No recommendation was produced for this project."}
        </p>
      </Card>
    );

  const criteria = Array.from(
    new Set(solutions.flatMap((s) => s.scores.map((sc) => sc.criterion)))
  );

  return (
    <div className="space-y-4">
      {recommendation?.recommended_option && (
        <Card className="border-brand-300 bg-brand-50/40">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-brand-600">
            Recommended
          </div>
          <div className="flex items-center gap-3">
            <h3 className="text-lg font-bold text-slate-900">
              {recommendation.recommended_option}
            </h3>
            <span className="rounded-full bg-brand-100 px-2 py-0.5 text-xs font-semibold text-brand-700">
              {Math.round(recommendation.confidence)}% confidence
            </span>
          </div>
          <p className="mt-2 text-sm text-slate-700">{recommendation.rationale}</p>
          {recommendation.why && (
            <p className="mt-2 text-sm text-slate-600">
              <span className="font-medium">Why: </span>
              {recommendation.why}
            </p>
          )}
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {recommendation.alternatives.length > 0 && (
              <MiniList title="Alternatives" items={recommendation.alternatives} />
            )}
            {recommendation.risks.length > 0 && (
              <MiniList title="Risks" items={recommendation.risks} />
            )}
          </div>
        </Card>
      )}

      {solutions.length > 0 && (
        <Card>
          <h3 className="mb-3 font-semibold text-slate-900">Solution Comparison</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="py-2 pr-3">Option</th>
                  {criteria.map((c) => (
                    <th key={c} className="px-3 py-2">{c}</th>
                  ))}
                  <th className="px-3 py-2">Pros</th>
                  <th className="px-3 py-2">Cons</th>
                </tr>
              </thead>
              <tbody>
                {solutions.map((s) => {
                  const scoreMap = Object.fromEntries(
                    s.scores.map((sc) => [sc.criterion, sc.rating])
                  );
                  return (
                    <tr key={s.id} className="border-b border-slate-100 align-top">
                      <td className="py-2 pr-3 font-medium text-slate-800">
                        {s.name}
                        {s.is_recommended && <span title="Recommended"> ⭐</span>}
                      </td>
                      {criteria.map((c) => (
                        <td key={c} className="px-3 py-2 text-slate-600">
                          {scoreMap[c] ?? "—"}
                        </td>
                      ))}
                      <td className="px-3 py-2 text-slate-600">{s.pros.slice(0, 2).join("; ") || "—"}</td>
                      <td className="px-3 py-2 text-slate-600">{s.cons.slice(0, 2).join("; ") || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {recommendation?.proof_of_concept && (
        <Card>
          <h3 className="mb-2 font-semibold text-slate-900">Proof of Concept</h3>
          <p className="text-sm text-slate-700">{recommendation.proof_of_concept}</p>
        </Card>
      )}

      {recommendation && recommendation.roadmap.length > 0 && (
        <Card>
          <h3 className="mb-3 font-semibold text-slate-900">Implementation Roadmap</h3>
          <ol className="space-y-2">
            {recommendation.roadmap.map((step, i) => (
              <li key={i} className="flex gap-3 text-sm">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-700">
                  {i + 1}
                </span>
                <div>
                  <span className="font-medium text-slate-800">{step.step}</span>
                  {step.detail && <span className="text-slate-600"> — {step.detail}</span>}
                </div>
              </li>
            ))}
          </ol>
        </Card>
      )}
    </div>
  );
}

function MiniList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div className="mb-1 text-xs font-semibold uppercase text-slate-500">{title}</div>
      <ul className="list-disc space-y-0.5 pl-5 text-sm text-slate-700">
        {items.map((it, i) => (
          <li key={i}>{it}</li>
        ))}
      </ul>
    </div>
  );
}

function GraphTab({ graph }: { graph: KnowledgeGraph | null }) {
  if (!graph || graph.nodes.length <= 1)
    return (
      <Card>
        <p className="text-sm text-slate-500">
          The knowledge graph appears once the research has produced solutions, claims,
          and a recommendation.
        </p>
      </Card>
    );
  return (
    <Card>
      <p className="mb-3 text-sm text-slate-500">
        How this project's topic, solutions, recommendation, claims, and sources relate.
      </p>
      <KnowledgeGraphView graph={graph} />
    </Card>
  );
}

// Failure card with the Retry action. Rendered only for a FAILED run (returns null
// otherwise, so it is never shown for completed/running research). Retry restarts the
// SAME project — distinct from "Research Again" (which forks a completed run).
export function FailedResearchCard({
  status,
  error,
  retrying,
  retryErr,
  onRetry,
}: {
  status: ProjectDetail["status"];
  error: string | null;
  retrying: boolean;
  retryErr: string | null;
  onRetry: () => void;
}) {
  if (status !== "failed") return null;
  return (
    <Card>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-red-700">Research Failed</h2>
          <p className="mt-1 text-sm text-slate-700">
            {error || "The research run stopped before completing."}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Fix the underlying issue (e.g. make sure Ollama is running), then retry. This
            restarts the same research; the original run is kept in its history.
          </p>
          {retryErr && <p className="mt-2 text-sm text-red-600">{retryErr}</p>}
        </div>
        <button
          onClick={onRetry}
          disabled={retrying}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <RefreshCw className={`h-4 w-4 ${retrying ? "animate-spin" : ""}`} />
          {retrying ? "Retrying…" : "Retry Research"}
        </button>
      </div>
    </Card>
  );
}

export function ReportTab({ report, isActive }: { report: Report | null; isActive: boolean }) {
  if (!report?.markdown)
    return (
      <Card>
        <p className="text-sm text-slate-500">
          {isActive
            ? "The report will appear here once research completes."
            : "No report available for this project."}
        </p>
      </Card>
    );
  return (
    <>
      {report.meta?.evidence_incomplete && (
        <div className="mb-4 flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <span aria-hidden>⚠️</span>
          <span>
            <strong>Research incomplete — no evidence was collected.</strong> No usable sources
            were retrieved for this run, so this report reflects the research plan only and is{" "}
            <strong>not an evidence-backed conclusion</strong>. See Research Health for why.
          </span>
        </div>
      )}
      {report.meta && (
        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <MetaStat label="Confidence" value={`${report.meta.overall_confidence}%`} />
          <MetaStat label="Sources" value={report.meta.sources_analyzed} />
          <MetaStat label="Verified Claims" value={report.meta.verified_claims} />
          <MetaStat label="Conflicts" value={report.meta.conflicted_claims} />
        </div>
      )}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-sm text-slate-500">Export:</span>
        {(["md", "html", "pdf", "docx"] as const).map((fmt) => (
          <a
            key={fmt}
            href={api.exportUrl(report.project_id, fmt)}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium uppercase text-slate-600 hover:bg-slate-100"
          >
            <Download className="h-3.5 w-3.5" /> {fmt}
          </a>
        ))}
      </div>
      <Card>
        <div className="markdown-body max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{report.markdown}</ReactMarkdown>
        </div>
      </Card>
    </>
  );
}

function MetaStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3">
      <div className="text-lg font-bold text-slate-900">{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  );
}

// --- Research monitoring (#6) --------------------------------------------- //
export function SeverityPill({ severity }: { severity: string | null | undefined }) {
  const m = severityMeta(severity as never);
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${m.className}`}
    >
      {m.icon} {m.label}
    </span>
  );
}

export function MonitoringTab({
  projectId,
  completed,
}: {
  projectId: string;
  completed: boolean;
}) {
  const [detail, setDetail] = useState<MonitorDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [frequency, setFrequency] = useState<MonitorFrequency>("daily");
  const [notifyPolicy, setNotifyPolicy] = useState<NotifyPolicy>("all");

  const load = useCallback(() => {
    setLoading(true);
    api
      .getMonitor(projectId)
      .then((d) => {
        setDetail(d);
        setNotFound(false);
      })
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false));
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  const createMonitor = async () => {
    setBusy(true);
    try {
      await api.createMonitor(projectId, {
        frequency,
        notify_policy: notifyPolicy,
        start: "scheduled",
      });
      load();
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (enabled: boolean) => {
    setBusy(true);
    try {
      await api.updateMonitor(projectId, { enabled });
      load();
    } finally {
      setBusy(false);
    }
  };

  const runNow = async () => {
    setBusy(true);
    try {
      await api.runMonitorNow(projectId);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await api.deleteMonitor(projectId);
      setDetail(null);
      setNotFound(true);
    } finally {
      setBusy(false);
    }
  };

  if (!completed) {
    return (
      <Card>
        <p className="text-sm text-slate-500">
          Monitoring watches a <em>completed</em> research run for meaningful changes.
          Finish this run first, then set up monitoring.
        </p>
      </Card>
    );
  }
  if (loading) return <Card><p className="text-sm text-slate-500">Loading…</p></Card>;

  // --- No monitor yet → setup. --- //
  if (notFound || !detail) {
    return (
      <Card>
        <div className="flex items-start gap-3">
          <Radar className="mt-0.5 h-5 w-5 text-brand-500" />
          <div className="flex-1">
            <h3 className="font-semibold text-slate-900">Monitor this research</h3>
            <p className="mt-1 text-sm text-slate-500">
              ResearchMind will re-check this topic on a schedule and alert you only when
              something <strong>meaningful</strong> changes — a claim gets contradicted,
              confidence shifts, the recommendation changes, or an authoritative new source
              appears. It won't ping you about search noise.
            </p>
            <div className="mt-4 flex flex-wrap items-end gap-4">
              <label className="text-sm">
                <span className="mb-1 block text-slate-600">Frequency</span>
                <select
                  value={frequency}
                  onChange={(e) => setFrequency(e.target.value as MonitorFrequency)}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
                >
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                </select>
              </label>
              <label className="text-sm">
                <span className="mb-1 block text-slate-600">Notify me about</span>
                <select
                  value={notifyPolicy}
                  onChange={(e) => setNotifyPolicy(e.target.value as NotifyPolicy)}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
                >
                  <option value="all">All meaningful changes</option>
                  <option value="important">Important changes only</option>
                  <option value="critical">Critical only</option>
                </select>
              </label>
              <button
                onClick={createMonitor}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
              >
                <Radar className="h-4 w-4" /> Start monitoring
              </button>
            </div>
          </div>
        </div>
      </Card>
    );
  }

  // --- Monitor exists → status + controls + history. --- //
  const m = detail.monitor;
  const hm = healthMeta(m.health);
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Radar className="h-5 w-5 text-brand-500" />
              <h3 className="font-semibold text-slate-900">Monitoring</h3>
              <span className={`inline-flex items-center gap-1.5 text-sm ${hm.className}`}>
                <span className={`h-2 w-2 rounded-full ${hm.dot}`} /> {hm.label}
              </span>
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
              <Field label="Schedule" value={FREQUENCY_LABEL[m.frequency] ?? m.frequency} />
              <Field label="Notify" value={NOTIFY_POLICY_LABEL[m.notify_policy] ?? m.notify_policy} />
              <Field label="Source policy" value={m.source_policy ?? "live preferred"} />
              <Field
                label="Last check"
                value={m.last_checked_at ? new Date(m.last_checked_at).toLocaleString() : "—"}
              />
              <Field label="Next check" value={new Date(m.next_check_at).toLocaleString()} />
              <Field label="Checks run" value={String(m.check_count)} />
            </dl>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={runNow}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              <RefreshCw className="h-4 w-4" /> Run now
            </button>
            <button
              onClick={() => toggle(!m.enabled)}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              {m.enabled ? "Pause" : "Resume"}
            </button>
            <button
              onClick={remove}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 disabled:opacity-50"
            >
              Remove
            </button>
          </div>
        </div>
      </Card>

      <div>
        <h4 className="mb-2 text-sm font-semibold text-slate-700">Recent checks</h4>
        {detail.recent_checks.length === 0 ? (
          <Card>
            <p className="text-sm text-slate-500">
              No checks yet. The first check will run on schedule (or press “Run now”).
            </p>
          </Card>
        ) : (
          <div className="space-y-2">
            {detail.recent_checks.map((c) => (
              <MonitorCheckRow key={c.id} check={c} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-slate-400">{label}</dt>
      <dd className="text-slate-700">{value}</dd>
    </div>
  );
}

export function MonitorCheckRow({ check }: { check: MonitorCheck }) {
  const [open, setOpen] = useState(false);
  const changes = check.meaningful_changes ?? [];
  const hasDetail = changes.length > 0;
  return (
    <Card className={check.status === "changes" ? "border-brand-300" : ""}>
      <button
        onClick={() => hasDetail && setOpen((v) => !v)}
        className="flex w-full items-center gap-3 text-left"
      >
        {hasDetail ? (
          open ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />
        ) : (
          <span className="h-4 w-4" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-slate-800">{checkStatusLabel(check.status)}</span>
            {check.max_impact && <SeverityPill severity={check.max_impact} />}
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
              {check.provenance_mode}
            </span>
          </div>
          <div className="mt-0.5 text-xs text-slate-400">
            {new Date(check.created_at).toLocaleString()}
            {check.suppressed_count > 0 && ` · ${check.suppressed_count} minor suppressed`}
          </div>
        </div>
        {check.new_run_id && check.baseline_run_id && (
          <Link
            to={`/research/${check.new_run_id}/diff/${check.baseline_run_id}`}
            onClick={(e) => e.stopPropagation()}
            className="inline-flex shrink-0 items-center gap-1 text-xs text-brand-600 hover:underline"
          >
            <GitCompare className="h-3.5 w-3.5" /> View diff
          </Link>
        )}
      </button>

      {open && hasDetail && (
        <ul className="mt-3 space-y-2 border-t border-slate-100 pt-3">
          {changes.map((ch, i) => (
            <li key={`${ch.dedup_key}-${i}`} className="flex items-start gap-2 text-sm">
              <SeverityPill severity={ch.impact} />
              <div className="min-w-0">
                <span className="font-medium text-slate-800">{ch.title}.</span>{" "}
                <span className="text-slate-600">{ch.detail}</span>
                {!ch.notified && (
                  <span className="ml-1 text-xs text-slate-400">(suppressed)</span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
