export type ResearchMode =
  | "quick"
  | "standard"
  | "deep"
  | "technical_rd"
  | "comparison"
  | "decision"
  | "market";

export type ProjectStatus =
  | "created"
  | "planning"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export type TaskStatus =
  | "pending"
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "retrying"
  | "paused"
  | "cancelled";

export type ClaimStatus =
  | "verified"
  | "partially_verified"
  | "conflicted"
  | "unverified"
  | "insufficient_evidence";

export type RunIntent = "original" | "refresh" | "deepen" | "verify" | "full";

export interface ProjectSummary {
  id: string;
  title: string;
  query: string;
  mode: ResearchMode;
  status: ProjectStatus;
  progress: number;
  current_stage: string | null;
  created_at: string;
  updated_at: string;
  // Research lineage (#4).
  parent_id: string | null;
  root_id: string | null;
  run_number: number;
  run_intent: RunIntent | null;
  completed_at: string | null;
}

export interface ProjectDetail extends ProjectSummary {
  objective: string | null;
  constraints: Record<string, unknown>;
  sources_enabled: string[];
  source_policy: SourcePolicy | null; // #5
  error: string | null;
  report_meta: ReportMeta | null;
}

export interface Question {
  id: string;
  text: string;
  priority: number;
  is_followup: boolean;
  answered: boolean;
}

export interface Task {
  id: string;
  agent: string;
  description: string;
  search_query: string | null;
  status: TaskStatus;
  attempts: number;
  round: number;
  error: string | null;
}

export type Freshness = "fresh" | "aging" | "stale" | "unknown";

// Connectivity Intelligence (#5).
export type Provenance =
  | "live_web"
  | "cached_web"
  | "local_document"
  | "local_memory"
  | "local_database";
export type Availability =
  | "live"
  | "cached"
  | "local"
  | "stale"
  | "unavailable"
  | "unknown";
export type ResearchHealth =
  | "fully_live"
  | "partially_degraded"
  | "cache_assisted"
  | "local_only"
  | "external_unavailable";
export type SourcePolicy =
  | "live_only"
  | "live_preferred"
  | "cache_allowed"
  | "local_only";

export interface Source {
  id: string;
  title: string;
  url: string;
  source_type: string;
  publisher: string | null;
  published_date: string | null;
  summary: string | null;
  reliability_score: number;
  relevance_score: number;
  freshness: Freshness;
  provenance: Provenance;
  availability: Availability;
  meta: Record<string, unknown>;
}

export type EvidenceState =
  | "supported"
  | "weak"
  | "conflicting"
  | "outdated"
  | "unverified";

export interface ConfidenceMeta {
  support_count: number;
  contradiction_count: number;
  avg_reliability: number;
  freshness: string;
  outdated: boolean;
  reasons: string[];
}

export interface Claim {
  id: string;
  text: string;
  status: ClaimStatus;
  confidence: number;
  supporting_source_ids: string[];
  confidence_meta: ConfidenceMeta | null;
  evidence_state: EvidenceState;
}

export type EvidenceStance = "supports" | "contradicts" | "neutral";

export interface ClaimEvidenceItem {
  source_id: string;
  title: string;
  url: string;
  source_type: string;
  publisher: string | null;
  published_date: string | null;
  reliability_score: number;
  freshness: Freshness;
  provenance: Provenance;
  availability: Availability;
  stance: EvidenceStance;
  passage: string | null;
  page_number: number | null;
}

export type DocumentStatus =
  | "uploaded"
  | "parsing"
  | "chunking"
  | "embedding"
  | "indexing"
  | "ready"
  | "failed";

export interface DocumentItem {
  id: string;
  project_id: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  status: DocumentStatus;
  page_count: number;
  word_count: number;
  chunk_count: number;
  error_message: string | null;
  processed_at: string | null;
  created_at: string;
  meta: Record<string, unknown>;
}

export interface DocumentPassage {
  document_id: string;
  chunk_id: string;
  filename: string;
  text: string;
  score: number;
  page_number: number | null;
  section: string | null;
}

export interface ClaimEvidenceResponse {
  claim: Claim;
  evidence: ClaimEvidenceItem[];
}

export interface SolutionScore {
  criterion: string;
  rating: string;
}

export interface Solution {
  id: string;
  name: string;
  description: string;
  pros: string[];
  cons: string[];
  risks: string[];
  scores: SolutionScore[];
  is_recommended: boolean;
}

export interface RoadmapStep {
  step: string;
  detail?: string;
}

export interface Recommendation {
  id: string;
  recommended_option: string;
  rationale: string;
  why: string;
  confidence: number;
  alternatives: string[];
  risks: string[];
  proof_of_concept: string;
  roadmap: RoadmapStep[];
}

export type ConflictSeverity = "high" | "medium" | "low";
export type ConflictStatus = "needs_verification" | "unresolved" | "resolved";

export interface Conflict {
  id: string;
  statement_a: string;
  statement_b: string;
  explanation: string;
  severity: ConflictSeverity;
  status: ConflictStatus;
  source_ids: string[];
}

export interface KnowledgeGap {
  id: string;
  question: string;
  reason: string;
  followup_query: string;
  round: number;
  resolved: boolean;
}

export interface SourceHealth {
  live: number;
  cached: number;
  local: number;
  stale: number;
  unknown: number;
  unavailable: number;
  provider_failures: number;
  fallback_count: number;
  retry_count: number;
  connectivity_state: string;
  research_mode: string; // live | hybrid | cache | local | unknown
  research_health: ResearchHealth;
}

export interface ReportMeta {
  overall_confidence: number;
  sources_analyzed: number;
  source_breakdown?: Record<string, number>;
  verified_claims: number;
  conflicted_claims: number;
  total_claims: number;
  source_health?: SourceHealth; // #5
}

export interface Report {
  project_id: string;
  markdown: string | null;
  meta: ReportMeta | null;
}

export interface CreateResearch {
  query: string;
  title?: string;
  mode: ResearchMode;
  sources_enabled: string[];
  constraints: Record<string, unknown>;
  auto_start: boolean;
  source_policy?: SourcePolicy; // #5; omit for backend default (live_preferred)
}

export interface Connectivity {
  enabled: boolean;
  overall_status: string;
  recovering?: boolean;
  internet?: boolean | null;
  providers?: { search: boolean | null };
  local_services?: {
    ollama: boolean | null;
    qdrant: boolean | null;
    database: boolean | null;
  };
  research_mode?: string;
}

export interface KnowledgeSearchResult {
  project_id: string;
  title: string;
  score: number | null;
  snippet: string;
  matches: number;
}

export interface KnowledgeStatus {
  enabled: boolean;
  semantic: boolean;
  embedding_model: string;
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  recommended?: boolean | null;
  status?: string | null;
  source_type?: string | null;
}

export interface GraphEdge {
  source: string;
  target: string;
  label: string;
}

export interface KnowledgeGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface MonitoringStats {
  projects: {
    total: number;
    by_status: Record<string, number>;
    completed: number;
    active_runs: number;
  };
  totals: { sources: number; claims: number; conflicts: number };
}

export interface AuditEntry {
  id: string;
  action: string;
  project_id: string | null;
  client_ip: string | null;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface HealthStatus {
  status: string;
  llm: { provider: string; model: string; reachable: boolean };
  knowledge: { enabled: boolean; embedding_model: string; semantic: boolean };
  search: { provider: string; configured: boolean };
  agents: Record<string, boolean>;
  github_token_configured: boolean;
}

export interface User {
  id: string;
  email: string;
  name: string;
  is_admin: boolean;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface Schedule {
  id: string;
  title: string;
  query: string;
  mode: ResearchMode;
  sources_enabled: string[];
  constraints: Record<string, unknown>;
  kind: "interval" | "once";
  interval_minutes: number | null;
  next_run_at: string;
  last_run_at: string | null;
  last_project_id: string | null;
  run_count: number;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ScheduleCreate {
  query: string;
  title?: string;
  mode: ResearchMode;
  sources_enabled: string[];
  constraints: Record<string, unknown>;
  kind: "interval" | "once";
  interval_minutes?: number | null;
  start_at?: string | null;
}

export interface Notification {
  id: string;
  type: string;
  title: string;
  message: string;
  project_id: string | null;
  read: boolean;
  created_at: string;
}

// --- Research Memory + Again + Diff (#4) ---------------------------------- //
export interface RunSummary {
  id: string;
  run_number: number;
  run_intent: RunIntent | null;
  status: ProjectStatus;
  created_at: string;
  completed_at: string | null;
  parent_id: string | null;
  source_count: number;
  claim_count: number;
  evidence_count: number;
  avg_confidence: number;
}

export interface ResearchAgainRequest {
  intent: "refresh" | "deepen" | "verify" | "full";
  mode?: ResearchMode;
  sources_enabled?: string[];
  auto_start?: boolean;
}

export interface MemorySummary {
  question: string;
  objective: string;
  key_findings: string[];
  high_confidence_claims: { text: string; confidence: number }[];
  weak_claims: { text: string; confidence: number }[];
  contradictions: { statement_a: string; statement_b: string }[];
  open_questions: string[];
  important_sources: { title: string; url: string; reliability: number }[];
  recommendation: { option: string; confidence: number } | null;
  counts: { sources: number; claims: number; evidence: number };
  confidence: { avg: number; supported: number; weak: number; conflicting: number };
  as_of: string;
}

export interface MemoryResponse {
  project_id: string;
  memory: MemorySummary | null;
}

export type DiffKind =
  | "unchanged"
  | "new"
  | "removed"
  | "changed"
  | "strengthened"
  | "weakened"
  | "contradicted"
  | "reversed"
  | "modified";

export interface DiffEvidenceItem {
  title: string;
  url: string;
  source_type: string;
  stance: EvidenceStance;
  passage: string | null;
  page_number: number | null;
}

export interface SourceDiffItem {
  kind: DiffKind;
  url: string;
  title: string;
  source_type: string;
  changes: string[];
}

export interface ClaimDiffItem {
  kind: DiffKind;
  old_text: string | null;
  new_text: string | null;
  old_confidence: number | null;
  new_confidence: number | null;
  confidence_delta: number | null;
  direction: "up" | "down" | "flat" | "";
  reason: string;
  match_score: number | null;
  old_evidence: DiffEvidenceItem[];
  new_evidence: DiffEvidenceItem[];
}

export interface DocumentDiffItem {
  kind: DiffKind;
  document_id: string | null;
  filename: string;
  changes: string[];
}

export interface ResearchDiff {
  old_run: { id: string; run_number: number; run_intent: string | null; completed_at: string | null };
  new_run: { id: string; run_number: number; run_intent: string | null; completed_at: string | null };
  sources: {
    new: number; removed: number; unchanged: number; changed: number;
    items: SourceDiffItem[];
  };
  claims: {
    new: number; removed: number; unchanged: number;
    strengthened: number; weakened: number; contradicted: number;
    items: ClaimDiffItem[];
  };
  confidence: { increased: number; decreased: number; unchanged: number };
  recommendation: {
    kind: DiffKind;
    old: { option: string; confidence: number } | null;
    new: { option: string; confidence: number } | null;
  };
  documents: {
    new: number; removed: number; unchanged: number; changed: number;
    items: DocumentDiffItem[];
  };
}

export interface ProgressEvent {
  project_id: string;
  type: string;
  message: string;
  data: Record<string, unknown>;
  timestamp: string;
}
