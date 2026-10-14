# R&D Laboratory Layer — Phase F Audit (Reproducibility, Versioning & Research History)

**STOP 1 — audit only. No production code, schema, API, frontend, or tests were changed.**

- **Baseline verified:** HEAD = `5a70ed1e26ea2a63b6258fc2373f5a906f7bd991` (Phase E). Working tree
  **clean**. `origin/master` 3 behind (Phase C/D/E not pushed — expected). Ancestry confirmed: A
  `1292e59`, B `37d9bbf`, C `8fafa26`, D `eb3d5a1`, E `5a70ed1` all ancestors-or-HEAD.
- **Method:** repository is the source of truth (`grep` + file reads over models/api/schemas/
  orchestrator/config).

## Existing state (confirmed by inspection)
- **No `ReproducibilityRecord` / verdict** anywhere (`grep -ril reproducib app/` → only the Phase C
  *docstring/field comments* in `models/experiment.py`).
- **Reproducibility METADATA fields exist on `Experiment`** (Phase C): `procedure`, `inputs`,
  `outputs`, `metrics`, `independent/dependent/controlled_variables`, `controls`, `assumptions`,
  `expected_result`, `hardware`, `software`, `software_versions`, `environment`, `configuration`,
  `seed`, `dataset_id`+`dataset_version`, `raw_data_reference`, `processed_data_reference`,
  execution fields (`started_at`/`completed_at`/`actual_result_summary`). These are **user-entered
  design/execution metadata**, free-text/JSON.
- **Object `version` counters:** only `ResearchBrief.version` (int, bumps on edit), `Method.version`
  (int, bumps on edit), `Dataset.version` (free-form string; a new version = a new row via
  `supersedes_id`). Everything else has **timestamps only** (`created_at`/`updated_at`).
- **`AuditLog`** (`action`, `project_id`, `user_id`, `client_ip`, `detail`, `created_at`): an
  action-level **audit trail** on create/start/stop/export/retry/brief.update — NOT a chronological
  research log/timeline.
- **The LLM model is a global config** (`config.ollama_model`), **not persisted per run/experiment**.
  No `git_commit` capture anywhere. `Dataset.checksum`, `Document.checksum` (sha256),
  `CachedSource.checksum` exist.
- **Run lineage (#4):** `ResearchProject.parent_id`/`root_id`/`run_number`/`run_intent`/`completed_at`/
  `memory_summary`; carry-forward documents/vectors; `research_diff`; completed runs are **immutable
  snapshots**.

## Findings by part

### 1–4. Reproducibility (metadata / record / verdict) — **PARTIAL metadata, MISSING record & verdict**
- Metadata: **PARTIAL** — rich design/execution fields on `Experiment`, but **not auto-captured** and
  missing structured **model/prompt/tool** capture (see §2) and git-commit.
- Reproducibility **record**: **MISSING** — no first-class object aggregating the reproduction snapshot.
- Reproducibility **verdict**: **MISSING** — no `not_assessed/reproducible/partially/not/inconclusive`
  state anywhere. (Correctly absent — must not be faked.)

### 2. Reproducibility metadata (by category)
| Category | Field | Status |
|---|---|---|
| AI/model | model name / version / provider | **MISSING** (global `config.ollama_model` only; not persisted per run/experiment) |
| AI/model | temperature / inference params | **MISSING** |
| AI/model | system/user prompt / template version | **MISSING** (prompts are in code, not versioned/captured) |
| AI/model | embedding model / version | **MISSING** (global config `nomic-embed-text`; not captured) |
| Tools | tool name / provider / config | **PARTIAL** (search provider is config; per-run capture MISSING; #11 eval used a *config id*, eval-only) |
| Tools | query / search date-time | **PARTIAL** (`ResearchTask.search_query` stored; explicit search timestamp MISSING) |
| Execution | method/procedure/inputs/outputs/metrics | **COMPLETE** (Experiment + Method) |
| Execution | dataset + dataset_version | **COMPLETE** (Experiment.dataset_id + dataset_version) |
| Execution | software/software_versions/hardware/env/config/seed | **PARTIAL** (fields exist on Experiment; manual, not auto-captured; no OS field) |
| Execution | timestamps | **COMPLETE** (created/updated/started/completed) |
| Data | source / source version | **PARTIAL** (Source + published_date; explicit "source version" MISSING) |
| Data | dataset / file checksum | **PARTIAL** (Dataset/Document/CachedSource checksums exist; optional/manual on Dataset) |
| Data | raw/processed refs / preprocessing | **COMPLETE** (Experiment + Dataset.preprocessing) |

### 3. Experiment reproducibility — DESIGN vs EXECUTION vs VERDICT
- **Design metadata: COMPLETE** (variables/controls/procedure/inputs/outputs/metrics/expected_result).
- **Execution record: PARTIAL** (status + started/completed_at + actual_result_summary + data refs
  exist and are set only by explicit PATCH — good; but no captured model/tool/git snapshot at run time).
- **Reproducibility verdict: MISSING.** An Experiment cannot yet state "reproducible/…"; nothing
  aggregates "exactly what another researcher needs."

### 4. Reproducibility verdict — **MISSING** (and must stay honest)
No verdict field/table. Correctly, a verdict must exist **only** with an explicit assessment basis —
"all metadata fields populated" is **not** proof of reproducibility. Any Phase F verdict must default
**not_assessed** and change only by explicit human/agent action.

### 5. Dataset versioning — **COMPLETE**
`Dataset.version` + `supersedes_id` (a new version is a new row; never overwritten). Experiments store
`dataset_id` + `dataset_version` (string snapshot), so an old experiment **can** identify exactly which
dataset version it used. `checksum` exists (optional). No further work required.

### 6. Object versioning matrix (RUN vs OBJECT vs HISTORY vs DIFF)
| Object | explicit version | timestamps | run lineage | immutable history | update history | diff |
|---|---|---|---|---|---|---|
| ResearchProject (=run) | run_number | ✅ | ✅ | ✅ (completed = immutable) | — | ✅ |
| ResearchBrief | ✅ int (bumps) | ✅ | via run | ❌ (no snapshots) | ❌ | ❌ |
| Method | ✅ int (bumps) | ✅ | via run | ❌ | ❌ | ❌ |
| Dataset | ✅ string (new row) | ✅ | via run | ✅ (supersedes_id) | ✅ | ❌ |
| Question/Objective/Constraint/Terminology | ❌ | ✅ | via run | ❌ | ❌ | ❌ |
| Hypothesis/Experiment/Result | ❌ | ✅ | via run | ❌ | ❌ | ❌ |
| Analysis/Conclusion | ❌ | ✅ | via run | ❌ | ❌ | ❌ |
| Recommendation | ❌ | ✅ | via run | ❌ | ❌ | ✅ (diff) |
| Comparison/Limitation/KnowledgeGap | ❌ | ✅ | via run | ❌ | ❌ | ❌ |
| Source/Claim | ❌ | ✅ | via run | ✅ (per-run rows) | ❌ | ✅ (diff) |
| Report | ❌ (no version field) | completed_at | ✅ (per run) | ✅ (per completed run) | ❌ | ✅ (via run diff) |
**Conclusion:** the system has strong **RUN versioning** (lineage + immutable completed runs) but weak
**OBJECT versioning** (only brief/method counters + dataset new-row) and **no per-object immutable
history/audit** beyond the run boundary. Timestamps ≠ versioning.

### 7. Run lineage — **COMPLETE** (reuse foundation)
parent/root/run_number/intent/completed_at/memory_summary/lineage grouping/carry-forward docs+vectors/
research_diff/run history all present (#4). This is the versioning foundation Phase F should build on —
**do not create another run/version system**.

### 8. Research history / log / timeline — **MISSING** (as a research log)
`AuditLog` is an **audit trail** (coarse actions), not a chronological **Research Log**
(search→source-found→evidence→claim-verified→experiment→result→decision→rejected-source→failure→retry).
No `TimelineEvent`/`ResearchLogEntry`. Ordinary server logs do **not** satisfy the requirement. **Note:**
this is the same scope as the plan's separate future milestone (Timeline/Research Log/lifecycle) — see
`RND-IMPLEMENTATION-PLAN.md` "PHASE E (plan) … FUTURE". Recommend **deferring** the full research
log/timeline to that milestone and keeping Phase F to reproducibility + versioning clarity.

### 9. Change tracking (diff) — **PARTIAL**
`research_diff` diffs sources/claims/recommendation/documents/confidence across two runs (deterministic).
The Phase B–E objects (methods/hypotheses/experiments/datasets/results/analysis/conclusions/comparisons/
limitations/gaps) are **not** diffed — explicitly deferred in prior phases. No second diff engine needed.

### 10. Report version history — **PARTIAL**
`report_markdown`/`report_meta` are the **current** projection per project and are overwritten (retry
keeps `retry_history` in `report_meta`). But each **run** is a separate project and completed runs are
immutable, so **historical reports are preserved per run** via lineage. No explicit `report_version`/
`generated_at` field (uses `completed_at`). Reports are **regenerated projections**, not stored
immutable snapshots within a run — acceptable given run-level immutability.

### 11. Provenance — **PARTIAL→COMPLETE (reuse)**
`Source.meta["provenance"]` (#5 live/cached/local); `origin` (user/agent/derived) on all Phase B–E
authored objects; claims via `ClaimSource` + `verification`. Missing: explicit provenance on report/
analysis/conclusion beyond `origin`. Reproducibility should **reuse** this — no second provenance system.

### 12. Secret handling — **SAFE today; must stay safe**
`SourceCache` stores content only (never keys/headers/cookies, #5); #11 manifest stored a provider
**config id**, never a key. `Experiment.environment`/`configuration` are user-entered (a user *could*
paste a secret, but the system never auto-captures secrets). **Boundary for Phase F:** capture model/
tool **names + versions + config ids + git commit** only — **never** API keys, tokens, cookies,
authorization headers, passwords, or raw env dumps.

### 13. Offline reproducibility — **PARTIAL**
Ollama model + embedding model are global config (`config.ollama_model`, `nomic-embed-text`), not
snapshotted per run; local file/document checksums exist (Document.checksum). Enough to reproduce
*locally* only if the config is recorded at run time — which it currently is **not**. Phase F should
auto-capture these safe, local values per run (no external dependency).

### 14. UI — reproducibility/history not surfaced
Experiment/Dataset/Result/Analysis/Conclusion/Recommendation/Comparison/Limitation/Gap panels exist
(Phases C–E); lineage bar + RunDiff + History page (#4) exist; no reproducibility panel. Reusable
patterns: `ExperimentsPanel`/`SynthesisPanel` card style; `RunDiff`/`History`/`LineageBar` for history.

### 15. API/Capability — no reproducibility/version/history endpoints
`api/rnd.py` has the object CRUD; `research.py` has runs/memory/diff. No reproducibility endpoint.
`/v1`+MCP exposure of R&D objects remains deferred (Phases B–E). Minimum future API: a reproducibility
record GET/PUT + verdict PATCH under `/research/{id}` (browser-facing `rnd.py`).

### 16. Knowledge Graph — no new entities required
Reproducibility/versioning are **metadata**, not graph relationships. `ResearchRun`/`*Version` KG
entities are **not** required by the master spec. Reuse run lineage + version metadata. **No KG change**
(and node emission remains Phase G anyway).

### 17. Database — minimal additive change
Only **one** genuinely-new table is needed (a reproducibility record). Everything else reuses run
lineage / timestamps / existing JSON (`report_meta`) / additive `version` columns. `create_all` +
`_ADDED_COLUMNS` conventions; Phase A–E data preserved.

### 18. Truthfulness risks (documented)
1. Claiming **"reproducible"** because metadata fields are populated → verdict must be explicit, default
   `not_assessed`, never inferred.
2. Claiming **"versioned"** when only timestamps exist → only objects with a real `version`/new-row/
   lineage may be described as versioned (per the §6 matrix).
3. Claiming **"historical"** when only current state exists → the (missing) research log must not be
   faked from server logs.
4. Claiming **"same dataset/experiment/model"** despite version/config/model-version differences →
   comparisons must key on version/commit, not names.
5. Fabricating a git commit / model version when unavailable → store `null`, never a placeholder.

## EXACT GAP MATRIX
| Requirement | Master spec | Existing impl | Files | Status | Required change | Reuse | Deferred |
|---|---|---|---|---|---|---|---|
| Reproducibility metadata | model/tool/env/data capture | Experiment fields (manual); global model config | `models/experiment.py`, `config.py` | **PARTIAL** | auto-capture safe run snapshot (model/embedding/git/as_of/provider-config-id) | Experiment fields; config; report_meta | prompt/template versioning |
| Reproducibility record | aggregated snapshot | none | — | **MISSING** | new `ReproducibilityRecord` (per run, optional experiment_id) | id-list validation, origin | — |
| Reproducibility verdict | explicit assessment | none | — | **MISSING** | `verdict` (default not_assessed) + assessed_by/notes/at; never auto-computed | 0–100 conventions | auto-scoring (never) |
| Dataset versioning | distinct versions | Dataset.version + supersedes_id | `models/experiment.py` | **COMPLETE** | none | — | — |
| Object versioning | per-object history | brief/method counters; dataset new-row; else timestamps | `models/*` | **PARTIAL** | rely on run lineage; add `version` only where edits need "what changed" | run lineage; existing counters | universal per-object snapshots |
| Run lineage | parent/root/run/diff | full (#4) | `models/research.py`, `research_diff.py` | **COMPLETE** | none | — | — |
| Research log / timeline | chronological research events | AuditLog (coarse audit) | `models/research.py` | **MISSING** | (defer) minimal event log or reuse AuditLog | AuditLog | **lifecycle milestone** |
| Change tracking (diff) | A vs B | sources/claims/rec/docs | `research_diff.py` | **PARTIAL** | none in F | existing diff | B–E object diff |
| Report versioning | per-version report | per-run immutable; overwritten within run | `orchestrator._build_report` | **PARTIAL** | optional `generated_at`; rely on lineage | lineage + completed_at | stored report snapshots |
| Provenance | per-object | Source provenance + origin | `services/provenance.py`, models | **PARTIAL→COMPLETE** | reuse | provenance/origin | report/analysis provenance |
| Secret safety | never store secrets | safe today | `source_cache`, #11 manifest | **COMPLETE (constraint)** | schema excludes secret fields | existing discipline | — |
| Offline repro metadata | local capture | global config only | `config.py` | **PARTIAL** | snapshot model/embedding/checksums per run | Document.checksum, config | — |

## ALTERNATIVE ARCHITECTURE ANALYSIS
- **A. Extend objects with version/history fields** — cheap; good for the *mutable authored* objects
  (bump `version` on edit). Insufficient alone for a reproducibility snapshot/verdict.
- **B. Generic research-object version table** — one table for all objects' versions. Powerful but
  **heavy/duplicative** (stores snapshots of everything), high migration/maintenance cost. **Reject for F.**
- **C. Immutable snapshots of every object** — even heavier than B; run lineage already gives immutable
  *run* snapshots. **Reject for F.**
- **D. Research event/audit-log table** — needed for the Research Log/Timeline, but that's the separate
  **lifecycle milestone**. **Defer.**
- **E. Reproducibility record** — a single first-class object capturing the snapshot + explicit verdict.
  Directly fills the core MISSING gap (Parts 1–4). **Recommended.**
- **F. Reuse run lineage + Diff** — already COMPLETE for run-level versioning/history/change-tracking.
  **Recommended as the versioning foundation** (don't rebuild).

## PROPOSED MINIMAL PHASE F ARCHITECTURE (E + F + light A)
1. **One new table `ReproducibilityRecord`** (per run; optional `experiment_id`; `project_id` FK):
   safe snapshot — `model_name`, `model_version`, `embedding_model`, `search_provider`,
   `provider_config_id` (never a key), `dataset_id`+`dataset_version`, `software_versions` (JSON),
   `hardware`, `os`, `environment` (label, not a secret dump), `configuration` (JSON, secret-free),
   `seed`, `git_commit`, `raw_data_reference`, `processed_data_reference`, `as_of` — plus
   `verdict` (default **`not_assessed`**; reproducible|partially_reproducible|not_reproducible|
   inconclusive), `assessed_by`, `assessment_notes`, `assessed_at`, `origin`. **Verdict never
   auto-computed.** Optionally auto-*create* one at run completion pre-filled with the safe
   auto-capturable values (model/embedding/git/as_of/provider-config-id), verdict=not_assessed.
2. **Reuse run lineage + `research_diff`** for run/object/report versioning, history-across-runs, and
   change tracking (no new run/version/diff engine).
3. **Light A:** add a `version` bump (like brief/method) to a small number of mutable authored objects
   only where "what changed on this object" matters (candidate: `Experiment`) — optional, minimal.
4. **API:** `GET/PUT /research/{id}/reproducibility` (+ optional `?experiment_id=`) and a verdict
   `PATCH`; ownership via `_get_project`; refs validated via existing helpers.
5. **Report:** an optional deterministic `## Reproducibility` section from the record (only when a record
   exists), clearly labelling `verdict` and never implying reproducibility from populated fields.
6. **UI:** a Reproducibility panel/section reusing existing card patterns; verdict badge.
7. **Secrets:** the record schema **excludes** any credential field; validate/strip on write.
8. **Tests:** record CRUD + verdict-defaults-not_assessed + no-auto-verdict + secret-safety +
   dataset-version identity + object-versioning-honesty + ownership/cross-project + offline + migration
   idempotency (A–E preserved).

## EXACT PHASE F SCOPE (proposed)
ReproducibilityRecord (snapshot + explicit verdict) + safe auto-capture at run completion + a minimal
`version` bump where justified + API + report section + UI + KG-none + tests. **Dataset/run versioning
already COMPLETE — no change.**

## EXPLICITLY DEFERRED
Full Research Log / Timeline / lifecycle / stage-recovery (separate milestone); B–E object diff/memory/
monitoring inclusion; universal per-object version-control (tables B/C); KG node emission (Phase G);
prompt/template versioning; `/v1`+MCP exposure; advanced statistical reproducibility; autonomous
execution/scheduling; decision intelligence; agent swarm; portfolio intelligence; org-wide KG;
governance/production-deploy redesign.

## ARCHITECTURAL BLOCKERS
**None.** One additive table + reuse of run lineage/diff/provenance/config. The only runtime nuance:
capturing `git_commit` reads repo HEAD at completion (safe, optional; store `null` if unavailable —
never fabricate). No second engine, no destructive migration, no secret storage.

---
**STOP 1 complete. No implementation performed. Awaiting authorization to implement Phase F.**
