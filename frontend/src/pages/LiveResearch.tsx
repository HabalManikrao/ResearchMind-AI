import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
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
  ReliabilityPill,
} from "../components/ui";
import KnowledgeGraphView from "../components/KnowledgeGraphView";
import DocumentsPanel from "../components/DocumentsPanel";
import type { KnowledgeGraph } from "../api/types";

type Tab =
  | "activity"
  | "plan"
  | "sources"
  | "documents"
  | "claims"
  | "conflicts"
  | "recommendation"
  | "graph"
  | "report";

const ACTIVE = ["running", "planning", "paused"];

export default function LiveResearch() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<ProjectDetail | null>(null);
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

  const isActive = project ? ACTIVE.includes(project.status) : false;
  const { events, progress, stage, finished } = useEventStream(id, isActive);

  const loadProject = useCallback(async () => {
    if (!id) return;
    const p = await api.getResearch(id);
    setProject(p);
    return p;
  }, [id]);

  const loadData = useCallback(async () => {
    if (!id) return;
    const [q, s, c, cf, g, sol, rec, r] = await Promise.all([
      api.questions(id),
      api.sources(id),
      api.claims(id),
      api.conflicts(id),
      api.gaps(id),
      api.solutions(id),
      api.recommendation(id),
      api.report(id),
    ]);
    setQuestions(q);
    setSources(s);
    setClaims(c);
    setConflicts(cf);
    setGaps(g);
    setSolutions(sol);
    setRecommendation(rec);
    setReport(r);
    // Graph is derived from stored rows; refresh it too (best-effort).
    api.knowledgeGraph(id).then(setGraph).catch(() => setGraph(null));
  }, [id]);

  // Initial load.
  useEffect(() => {
    loadProject().then((p) => {
      if (p && p.status === "completed") setTab("report");
    });
    loadData();
  }, [loadProject, loadData]);

  // While active, refresh detail + data periodically so plan/sources/claims populate live.
  useEffect(() => {
    if (!isActive) return;
    const t = setInterval(() => {
      loadProject();
      loadData();
    }, 4000);
    return () => clearInterval(t);
  }, [isActive, loadProject, loadData]);

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

  if (!project) return <p className="text-slate-500">Loading…</p>;

  const displayProgress = isActive ? Math.max(progress, project.progress) : project.progress;

  const TABS: { key: Tab; label: string; count?: number }[] = [
    { key: "activity", label: "Activity" },
    { key: "plan", label: "Plan", count: questions.length },
    { key: "sources", label: "Sources", count: sources.length },
    { key: "documents", label: "Documents" },
    { key: "claims", label: "Claims", count: claims.length },
    { key: "conflicts", label: "Conflicts", count: conflicts.length },
    { key: "recommendation", label: "Recommendation" },
    { key: "graph", label: "Graph" },
    { key: "report", label: "Report" },
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
    </div>
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

function ReportTab({ report, isActive }: { report: Report | null; isActive: boolean }) {
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
