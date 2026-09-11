"""The research pipeline: plan -> research -> verify -> gap loop -> report.

Runs as a background task. All state is persisted to the DB as it progresses so a
run is resumable and observable. Progress is streamed via the event bus.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import delete as sa_delete, select

from app.agents import (
    conflict_detection,
    contradiction,
    dispatch,
    gap_analysis,
    planner,
    rd_analysis,
    report,
    verification,
)
from app.agents.common import AGENT_LABELS
from app.agents.conflict_detection import ClaimRef
from app.agents.verification import EvidenceSource, score_claim
from app.config import get_settings
from app.database import SessionLocal
from app.llm import get_provider
from app.models import (
    Claim,
    ClaimSource,
    ClaimStatus,
    Conflict,
    EvidenceStance,
    Finding,
    KnowledgeGap,
    ProjectStatus,
    Recommendation,
    ResearchMode,
    ResearchProject,
    ResearchQuestion,
    ResearchTask,
    Solution,
    Source,
    TaskStatus,
)
from app.services import connectivity, dedup, notifications, provenance
from app.services.collection import resilient_collect
from app.knowledge import graph as kg_graph
from app.knowledge import service as knowledge
from app.knowledge.service import KnowledgeUnavailable
from app.models.enums import SourcePolicy
from app.orchestration.control import Cancelled, RunControl
from app.search import get_search_client
from app.services.events import ProgressEvent, bus

settings = get_settings()
_db_lock = asyncio.Lock()  # serialize SQLite writes across concurrent tasks

# How many of the top-priority questions each source type researches in the initial
# round. Sources are filled in this order until the global task budget is reached,
# so the highest-value source (web) is never starved by the cap.
SOURCE_QUESTION_BUDGET = {
    "web": 8,
    "documents": 5,
    "docs": 3,
    "github": 3,
    "papers": 3,
    "news": 2,
    "community": 3,
}
# "documents" (local uploads) sits high so document evidence isn't starved by the budget.
SOURCE_ORDER = ["web", "documents", "docs", "github", "papers", "news", "community"]


async def _emit(project_id: str, type_: str, message: str, **data) -> None:
    await bus.publish(ProgressEvent(project_id=project_id, type=type_, message=message, data=data))


async def _set_progress(project_id: str, progress: int, stage: str) -> None:
    async with _db_lock, SessionLocal() as db:
        proj = await db.get(ResearchProject, project_id)
        if proj:
            proj.progress = progress
            proj.current_stage = stage
            await db.commit()
    await _emit(project_id, "progress", stage, progress=progress, stage=stage)


async def run_research(project_id: str, control: RunControl) -> None:
    provider = get_provider()
    tavily = get_search_client(settings)
    try:
        async with SessionLocal() as db:
            proj = await db.get(ResearchProject, project_id)
            if proj is None:
                return
            proj.status = ProjectStatus.PLANNING
            await db.commit()
            query = proj.query
            constraints = dict(proj.constraints or {})
            enabled_sources = list(proj.sources_enabled or ["web"])
            mode = proj.mode
            parent_id = proj.parent_id
            run_intent = proj.run_intent or "original"
            owner_id = proj.user_id
            policy = proj.source_policy or settings.default_source_policy

        # --- Connectivity Intelligence (#5): understand availability up front ---
        # A single cached snapshot steers policy fallback and the run-health summary;
        # it never blocks the run — resilient_collect handles per-source fallback.
        run_stats = {"fallback": 0, "retries": 0, "provider_failures": 0}
        snapshot = None
        if settings.connectivity_enabled:
            try:
                snapshot = await connectivity.manager.snapshot()
            except Exception:  # noqa: BLE001 - probing must never sink a run
                snapshot = None
        if snapshot is not None:
            eff_mode = connectivity.research_mode_for(snapshot, policy)
            await _emit(
                project_id, "activity",
                f"Connectivity: {snapshot.overall} → {eff_mode} research "
                f"(policy: {policy})",
                agent="connectivity", overall=snapshot.overall, mode=eff_mode,
                policy=policy, layers=snapshot.layers,
            )

        # Market Intelligence mode: bias search toward recent sources and report a
        # dated snapshot of the current state.
        is_market = mode == ResearchMode.MARKET
        as_of = datetime.now(timezone.utc).date().isoformat()
        recency_days = settings.market_recency_days if is_market else None

        await _emit(project_id, "stage", "Understanding objective and planning research")
        await control.checkpoint()

        # --- Prior context (Research Again): steer planning with the parent run's
        # selective memory. Zero extra LLM calls — injected into make_plan (#4). ----
        prior_context = None
        if parent_id:
            prior_context = await _build_prior_context(parent_id)
            if prior_context:
                await _emit(
                    project_id, "activity",
                    f"Continuing previous research ({run_intent}) with prior context",
                    agent="manager", intent=run_intent, parent_id=parent_id,
                )

        # --- Plan -------------------------------------------------------------
        brief_context = await _build_brief_context(project_id)  # R&D Phase A (deterministic)
        plan = await planner.make_plan(
            provider, query, constraints=constraints, market=is_market, as_of=as_of,
            prior_context=prior_context, intent=run_intent, brief_context=brief_context,
        )
        async with _db_lock, SessionLocal() as db:
            proj = await db.get(ResearchProject, project_id)
            proj.objective = plan.objective
            proj.status = ProjectStatus.RUNNING
            for pq in plan.questions:
                db.add(
                    ResearchQuestion(
                        project_id=project_id,
                        text=pq.text,
                        priority=pq.priority,
                    )
                )
            await db.commit()
        await _emit(
            project_id, "activity",
            f"Research Planner created {len(plan.questions)} research questions",
            agent="planner", count=len(plan.questions),
        )
        await _set_progress(project_id, 15, "Research plan ready")

        # --- Knowledge reuse: surface related prior research (spec §14) -------
        await _surface_related_research(project_id, plan.objective)

        # --- Create initial tasks across enabled source agents ---------------
        n_tasks = await _create_tasks(project_id, plan.questions, enabled_sources, round_=0)
        active_agents = sorted(
            {s for s in enabled_sources if s in SOURCE_QUESTION_BUDGET}
        )
        await _emit(
            project_id, "activity",
            f"Dispatched {n_tasks} tasks across {len(active_agents)} agents: "
            + ", ".join(AGENT_LABELS.get(s, s) for s in active_agents),
            agent="manager", tasks=n_tasks, agents=active_agents,
        )

        # --- Research + follow-up loop ---------------------------------------
        for round_ in range(settings.max_followup_rounds + 1):
            await control.checkpoint()
            pending = await _pending_tasks(project_id)
            if not pending:
                break
            base = 15 + round_ * 25
            await _run_tasks(
                project_id, pending, provider, tavily, control,
                base_progress=base, recency_days=recency_days,
                policy=policy, user_id=owner_id, run_stats=run_stats,
            )

            # Verify accumulated evidence.
            await control.checkpoint()
            await _emit(project_id, "stage", "Verifying claims across sources")
            await _verify(project_id, provider)
            await _set_progress(project_id, min(85, base + 20), "Claims verified")

            # Gap analysis -> follow-up tasks (skipped on the final allowed round).
            if round_ < settings.max_followup_rounds:
                await control.checkpoint()
                await _emit(project_id, "stage", "Analyzing knowledge gaps")
                added = await _gap_followup(project_id, provider, round_ + 1)
                if added:
                    await _emit(
                        project_id, "activity",
                        f"Knowledge-gap analysis created {added} follow-up task(s)",
                        agent="gap_analysis", count=added,
                    )
                else:
                    break  # no gaps -> stop looping early

        # --- Connectivity recovery (#5, spec §26): if external tasks failed and the
        # provider is healthy again, retry the failed ones once. Historical evidence
        # is untouched; a no-op when nothing failed. ---------------------------
        await control.checkpoint()
        n_recovered = await _retry_failed_external(
            project_id, provider, tavily, control, policy, owner_id, run_stats, recency_days,
        )
        if n_recovered:
            await _emit(
                project_id, "activity",
                f"Connectivity recovered — retried {n_recovered} previously failed source task(s)",
                agent="connectivity", recovered=n_recovered,
            )
            # Recovered sources are folded into claims by the dedupe→re-verify below.

        # --- Deduplicate collected information --------------------------------
        await control.checkpoint()
        await _emit(project_id, "stage", "Removing duplicate sources and findings")
        stats = await dedup.dedupe_project(project_id)
        if stats["sources_removed"] or stats["findings_removed"]:
            await _emit(
                project_id, "activity",
                f"Deduplication removed {stats['sources_removed']} duplicate source(s) "
                f"and {stats['findings_removed']} duplicate finding(s)",
                agent="dedup", **stats,
            )
        # Rebuild claims on the deduplicated evidence.
        await _verify(project_id, provider)
        await _set_progress(project_id, 86, "Deduplicated & re-verified")

        # --- Active contradiction search -------------------------------------
        # Seek disconfirming evidence for the key claims so confidence isn't high
        # just because nobody looked for the counter-argument (spec §23.3).
        await control.checkpoint()
        await _emit(project_id, "stage", "Searching for contradicting evidence")
        # Contradiction search is an enhancement, not a gate: an error here must
        # never sink an otherwise-complete run. (Cancellation still propagates.)
        try:
            n_contra = await _seek_contradictions(project_id, provider, tavily)
        except Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            n_contra = 0
            await _emit(
                project_id, "activity",
                f"Contradiction search skipped after an error: {exc}",
                agent="contradiction", failed=True,
            )
        if n_contra:
            await _emit(
                project_id, "activity",
                f"Contradiction search surfaced {n_contra} disconfirming source(s)",
                agent="contradiction", count=n_contra,
            )
        await _set_progress(project_id, 87, "Contradiction check complete")

        # --- Conflict detection ----------------------------------------------
        await control.checkpoint()
        await _emit(project_id, "stage", "Detecting conflicting information")
        n_conflicts = await _detect_conflicts(project_id, provider)
        if n_conflicts:
            await _emit(
                project_id, "activity",
                f"Conflict detection found {n_conflicts} contradiction(s)",
                agent="conflict_detection", count=n_conflicts,
            )
        await _set_progress(project_id, 88, "Conflict analysis complete")

        # --- R&D analysis: comparison, recommendation, delivery plan ----------
        await control.checkpoint()
        await _emit(project_id, "stage", "Comparing solutions and forming a recommendation")
        rec_name = await _rd_analysis(project_id, provider)
        if rec_name:
            await _emit(
                project_id, "activity",
                f"R&D analysis recommends: {rec_name}",
                agent="rd_analysis", recommendation=rec_name,
            )
        await _set_progress(project_id, 92, "R&D analysis complete")

        # --- Source health summary (#5, spec §22, §23, §40): live/cached/local/
        # stale/unavailable counts + a run-level health label, computed from the
        # actual persisted sources and failed tasks. Fed to the report for honest
        # disclosure (§15) and surfaced in report_meta + UI. ------------------
        source_health = await _build_source_health(project_id, snapshot, run_stats)
        await _emit(
            project_id, "activity",
            "Source health — "
            f"live: {source_health['live']}, cached: {source_health['cached']}, "
            f"local: {source_health['local']}, unavailable: {source_health['unavailable']}, "
            f"stale: {source_health['stale']}",
            agent="connectivity", **source_health,
        )

        # --- Report -----------------------------------------------------------
        await control.checkpoint()
        await _emit(project_id, "stage", "Generating final research report")
        await _set_progress(project_id, 95, "Generating report")
        await _build_report(project_id, provider, source_health)

        # --- Build the compact research-memory record from the finalized rows --
        memory_summary = await _build_memory_summary(project_id, as_of)

        async with _db_lock, SessionLocal() as db:
            proj = await db.get(ResearchProject, project_id)
            proj.status = ProjectStatus.COMPLETED
            proj.progress = 100
            proj.current_stage = "Completed"
            proj.completed_at = datetime.now(timezone.utc)
            proj.memory_summary = memory_summary
            await db.commit()
            owner_id, proj_title = proj.user_id, proj.title

        # --- Index into the knowledge base for future reuse (spec §14) -------
        await _index_knowledge(project_id)

        # --- Update the temporal knowledge graph (#7). Best-effort: a graph failure
        # never fails the run; a continuation reconciles against its parent via the
        # existing Research Diff. Status is recorded in report_meta (§20, §32). --------
        await _update_knowledge_graph(project_id, parent_id)

        await _emit(project_id, "done", "Research complete", progress=100)
        await notifications.notify(
            owner_id, type="research_completed", project_id=project_id,
            title="Research complete", message=f"“{proj_title}” finished successfully.",
        )

    except Cancelled:
        async with _db_lock, SessionLocal() as db:
            proj = await db.get(ResearchProject, project_id)
            if proj and proj.status not in (ProjectStatus.COMPLETED,):
                proj.status = ProjectStatus.CANCELLED
                proj.current_stage = "Cancelled"
                await db.commit()
        await _emit(project_id, "error", "Research cancelled")
    except Exception as exc:  # noqa: BLE001 - surface any failure to the user
        owner_id = proj_title = None
        async with _db_lock, SessionLocal() as db:
            proj = await db.get(ResearchProject, project_id)
            if proj:
                proj.status = ProjectStatus.FAILED
                proj.error = str(exc)
                proj.current_stage = "Failed"
                await db.commit()
                owner_id, proj_title = proj.user_id, proj.title
        await _emit(project_id, "error", f"Research failed: {exc}")
        await notifications.notify(
            owner_id, type="research_failed", project_id=project_id,
            title="Research failed", message=f"“{proj_title}” failed: {exc}",
        )


# Transient rows a run appends that would be DUPLICATED if run_research ran again on the
# same project (sources/findings/questions/gaps/tasks are append-only; claims/conflicts/
# solutions/recommendations are delete-first in the pipeline but cleared here too so a
# re-run that fails early can't leave stale analysis behind). ClaimSource has no
# project_id, so it is deleted via its claim ids first.
_RETRY_RESET_MODELS = (
    Claim, Conflict, Recommendation, Solution, Finding, Source,
    KnowledgeGap, ResearchTask, ResearchQuestion,
)


async def reset_project_for_retry(project_id: str) -> bool:
    """Reset a FAILED run's transient execution state so it can be retried IN PLACE.

    Retry restarts the SAME project — it is not Research Again (which forks a new run
    from a COMPLETED one). ``run_research`` assumes a fresh project and never resets, and
    some collection rows are append-only (so a naive re-run would duplicate them and the
    task-budget cap could starve the retry). This clears exactly that transient state
    under ``_db_lock``, PRESERVES the original failure in ``report_meta["retry_history"]``
    (never silently erased), and flips the run to PLANNING so the UI treats it as active
    immediately (``run_research`` sets PLANNING again — idempotent).

    Returns ``False`` if the project is missing or no longer FAILED (e.g. a concurrent
    retry won the race), so the caller can reject the duplicate without starting a run.
    """
    async with _db_lock, SessionLocal() as db:
        proj = await db.get(ResearchProject, project_id)
        if proj is None or proj.status != ProjectStatus.FAILED:
            return False

        # Preserve the failure before clearing it (spec: do not silently erase).
        meta = dict(proj.report_meta or {})
        history = list(meta.get("retry_history") or [])
        history.append({
            "error": proj.error,
            "stage": proj.current_stage,
            "retried_at": datetime.now(timezone.utc).isoformat(),
        })
        meta["retry_history"] = history
        proj.report_meta = meta

        # Delete claim evidence links first (no project_id → key off the project's claims).
        claim_ids = (
            await db.execute(select(Claim.id).where(Claim.project_id == project_id))
        ).scalars().all()
        if claim_ids:
            await db.execute(
                sa_delete(ClaimSource).where(ClaimSource.claim_id.in_(claim_ids))
            )
        for model in _RETRY_RESET_MODELS:
            await db.execute(sa_delete(model).where(model.project_id == project_id))

        proj.status = ProjectStatus.PLANNING
        proj.error = None
        proj.progress = 0
        proj.current_stage = "Retrying"
        proj.report_markdown = None
        await db.commit()
    return True


# --------------------------------------------------------------------------- #
# Stage helpers
# --------------------------------------------------------------------------- #
async def _create_tasks(project_id: str, questions, enabled_sources, round_: int) -> int:
    """Create one task per (source, top-priority-question) pair, filling the global
    task budget source-by-source in SOURCE_ORDER. Returns the number created."""
    # Canonical, de-duplicated source list; default to web if none selected.
    sources = [s for s in SOURCE_ORDER if s in set(enabled_sources)] or ["web"]
    ranked = sorted(questions, key=lambda q: q.priority)

    created = 0
    async with _db_lock, SessionLocal() as db:
        q_rows = (
            await db.execute(
                select(ResearchQuestion).where(ResearchQuestion.project_id == project_id)
            )
        ).scalars().all()
        by_text = {r.text: r for r in q_rows}
        existing = (
            await db.execute(
                select(ResearchTask).where(ResearchTask.project_id == project_id)
            )
        ).scalars().all()
        remaining = settings.max_research_tasks - len(existing)

        for source in sources:
            budget = SOURCE_QUESTION_BUDGET.get(source, 3)
            for pq in ranked[:budget]:
                if remaining <= 0:
                    break
                row = by_text.get(pq.text)
                db.add(
                    ResearchTask(
                        project_id=project_id,
                        question_id=row.id if row else None,
                        agent=source,
                        description=f"[{AGENT_LABELS.get(source, source)}] {pq.text}",
                        search_query=pq.search_query,
                        status=TaskStatus.PENDING,
                        round=round_,
                    )
                )
                remaining -= 1
                created += 1
        await db.commit()
    return created


async def _pending_tasks(project_id: str) -> list[dict]:
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(ResearchTask).where(
                    ResearchTask.project_id == project_id,
                    ResearchTask.status.in_([TaskStatus.PENDING, TaskStatus.RETRYING]),
                )
            )
        ).scalars().all()
        return [
            {
                "id": t.id,
                "question_id": t.question_id,
                "search_query": t.search_query,
                "description": t.description,
                "agent": t.agent,
            }
            for t in rows
        ]


async def _run_tasks(
    project_id, tasks, provider, tavily, control, *, base_progress, recency_days=None,
    policy=SourcePolicy.LIVE_PREFERRED.value, user_id=None, run_stats=None,
) -> None:
    sem = asyncio.Semaphore(4)
    total = len(tasks)
    done = 0

    async def worker(task: dict) -> None:
        nonlocal done
        await control.checkpoint()
        async with sem:
            agent = task["agent"]
            label = AGENT_LABELS.get(agent, agent)
            await _mark_task(task["id"], TaskStatus.RUNNING, inc_attempt=True)
            question_text = await _question_text(task)
            try:
                # Resilient collection (#5): live → cache → (local agents are offline).
                # Provenance is stamped inside; the outcome drives run-health accounting.
                result = await resilient_collect(
                    agent, provider, tavily, settings,
                    question=question_text,
                    search_query=task["search_query"] or question_text,
                    recency_days=recency_days,
                    project_id=project_id,
                    user_id=user_id,
                    policy=policy,
                )
                sources = result.sources
                await _persist_sources(project_id, task, sources)
                await _mark_task(task["id"], TaskStatus.COMPLETED)
                if run_stats is not None and result.outcome == "cached":
                    run_stats["fallback"] = run_stats.get("fallback", 0) + 1
                suffix = {
                    "cached": " (served from cache — live source unavailable)",
                    "skipped": " (external source skipped — local-only policy)",
                }.get(result.outcome, "")
                await _emit(
                    project_id, "activity",
                    f"{label} analyzed {len(sources)} source(s) for: "
                    f"{question_text[:80]}{suffix}",
                    agent=agent, sources=len(sources), outcome=result.outcome,
                )
                if task["question_id"] and sources:
                    await _mark_question_answered(task["question_id"])
            except Exception as exc:  # noqa: BLE001
                await _mark_task(task["id"], TaskStatus.FAILED, error=str(exc))
                if run_stats is not None and provenance.is_external(agent):
                    run_stats["provider_failures"] = run_stats.get("provider_failures", 0) + 1
                await _emit(
                    project_id, "activity",
                    f"{label} task failed: {exc}", agent=agent, failed=True,
                )
        done += 1
        pct = base_progress + int((done / total) * 20) if total else base_progress
        await _set_progress(project_id, min(pct, base_progress + 20), "Collecting & extracting sources")

    await asyncio.gather(*(worker(t) for t in tasks))


async def _persist_sources(project_id, task, sources) -> None:
    async with _db_lock, SessionLocal() as db:
        for es in sources:
            src = Source(
                project_id=project_id,
                task_id=task["id"],
                title=es.title,
                url=es.url,
                source_type=es.source_type,
                published_date=es.published_date,
                content=es.content[:20000] if es.content else None,
                summary=es.summary,
                reliability_score=es.reliability_score,
                relevance_score=es.relevance_score,
                meta=es.meta or {},
            )
            db.add(src)
            await db.flush()  # get src.id
            for f in es.findings:
                db.add(
                    Finding(
                        project_id=project_id,
                        source_id=src.id,
                        question_id=task["question_id"],
                        text=f,
                        relevance_score=es.relevance_score,
                    )
                )
        await db.commit()


async def _verify(project_id, provider) -> None:
    as_of = datetime.now(timezone.utc).date()
    async with SessionLocal() as db:
        findings = (
            await db.execute(select(Finding).where(Finding.project_id == project_id))
        ).scalars().all()
        sources = (
            await db.execute(select(Source).where(Source.project_id == project_id))
        ).scalars().all()

    if not findings:
        return
    src_by_id = {s.id: s for s in sources}
    # Assign each source a stable evidence index.
    idx_by_source = {sid: i for i, sid in enumerate(src_by_id)}

    pairs: list[tuple[str, EvidenceSource]] = []
    for f in findings:
        s = src_by_id.get(f.source_id)
        if not s:
            continue
        pairs.append(
            (
                f.text,
                EvidenceSource(
                    index=idx_by_source[s.id],
                    source_id=s.id,
                    url=s.url,
                    reliability=s.reliability_score,
                    published_date=s.published_date,
                    source_type=s.source_type,
                ),
            )
        )

    claims = await verification.verify(provider, pairs, as_of=as_of)

    async with _db_lock, SessionLocal() as db:
        # Replace prior claims for idempotency across follow-up rounds. Delete the
        # evidence links explicitly first (passive_deletes avoids an async-unsafe
        # lazy load), then the claims.
        existing = (
            await db.execute(select(Claim).where(Claim.project_id == project_id))
        ).scalars().all()
        old_ids = [c.id for c in existing]
        if old_ids:
            await db.execute(
                sa_delete(ClaimSource).where(ClaimSource.claim_id.in_(old_ids))
            )
        for c in existing:
            await db.delete(c)
        await db.flush()
        for vc in claims:
            claim = Claim(
                project_id=project_id,
                text=vc.text,
                status=vc.status,
                confidence=vc.confidence,
                supporting_source_ids=vc.supporting_source_ids,
                confidence_meta=vc.confidence_meta,
            )
            db.add(claim)
            await db.flush()  # get claim.id
            for ev in vc.evidence:
                db.add(
                    ClaimSource(
                        claim_id=claim.id,
                        source_id=ev.source_id,
                        stance=EvidenceStance(ev.stance),
                        passage=ev.passage or None,
                    )
                )
        await db.commit()
    await _emit(
        project_id, "activity",
        f"Verification agent consolidated {len(claims)} claim(s)",
        agent="verification", count=len(claims),
    )


async def _seek_contradictions(project_id, provider, search_client) -> int:
    """Active contradiction search: for the top high-confidence claims, look for
    disconfirming evidence, persist it as CONTRADICTS evidence links, and re-score
    the affected claims. Returns the number of contradicting sources added."""
    if not settings.contradiction_search_enabled:
        return 0
    as_of = datetime.now(timezone.utc).date()

    async with SessionLocal() as db:
        claims = (
            await db.execute(select(Claim).where(Claim.project_id == project_id))
        ).scalars().all()
        sources = (
            await db.execute(select(Source).where(Source.project_id == project_id))
        ).scalars().all()
    src_by_id = {s.id: s for s in sources}

    important = sorted(
        (
            c
            for c in claims
            if c.status
            in (ClaimStatus.VERIFIED, ClaimStatus.PARTIALLY_VERIFIED)
            and c.confidence >= settings.contradiction_min_confidence
        ),
        key=lambda c: c.confidence,
        reverse=True,
    )[: settings.max_contradiction_checks]
    if not important:
        return 0

    results = await contradiction.seek(
        provider,
        search_client,
        [(c.id, c.text) for c in important],
        max_results=settings.max_sources_per_task,
    )
    if not results:
        return 0

    added = 0
    async with _db_lock, SessionLocal() as db:
        for cc in results:
            claim = await db.get(Claim, cc.claim_id)
            if claim is None:
                continue
            contra_es: list[EvidenceSource] = []
            for cs in cc.sources:
                src = Source(
                    project_id=project_id,
                    task_id=None,
                    title=cs.title,
                    url=cs.url,
                    source_type=cs.source_type,
                    published_date=cs.published_date,
                    content=cs.content[:20000] if cs.content else None,
                    summary=cs.passage or None,
                    reliability_score=cs.reliability,
                    relevance_score=0.0,
                    meta={"contradiction": True},
                )
                db.add(src)
                await db.flush()  # get src.id
                db.add(
                    ClaimSource(
                        claim_id=claim.id,
                        source_id=src.id,
                        stance=EvidenceStance.CONTRADICTS,
                        passage=cs.passage or None,
                    )
                )
                contra_es.append(
                    EvidenceSource(
                        index=-1,
                        source_id=src.id,
                        url=cs.url,
                        reliability=cs.reliability,
                        published_date=cs.published_date,
                        source_type=cs.source_type,
                    )
                )
                added += 1

            # Rebuild the supporting evidence and re-score with contradictions.
            supp_links = (
                await db.execute(
                    select(ClaimSource).where(
                        ClaimSource.claim_id == claim.id,
                        ClaimSource.stance == EvidenceStance.SUPPORTS,
                    )
                )
            ).scalars().all()
            supp_es: list[EvidenceSource] = []
            for link in supp_links:
                s = src_by_id.get(link.source_id) or await db.get(Source, link.source_id)
                if s is None:
                    continue
                supp_es.append(
                    EvidenceSource(
                        index=-1,
                        source_id=s.id,
                        url=s.url,
                        reliability=s.reliability_score,
                        published_date=s.published_date,
                        source_type=s.source_type,
                    )
                )
            status, confidence, meta = score_claim(
                supp_es, contra_es, conflicting=False, as_of=as_of
            )
            claim.status = status
            claim.confidence = confidence
            claim.confidence_meta = meta
        await db.commit()
    return added


async def _detect_conflicts(project_id, provider) -> int:
    async with SessionLocal() as db:
        claims = (
            await db.execute(select(Claim).where(Claim.project_id == project_id))
        ).scalars().all()

    refs = [
        ClaimRef(index=i, text=c.text, source_ids=list(c.supporting_source_ids or []))
        for i, c in enumerate(claims)
    ]
    detected = await conflict_detection.detect(provider, refs)

    async with _db_lock, SessionLocal() as db:
        # Rebuild for idempotency across re-runs.
        existing = (
            await db.execute(select(Conflict).where(Conflict.project_id == project_id))
        ).scalars().all()
        for c in existing:
            await db.delete(c)
        for dc in detected:
            db.add(
                Conflict(
                    project_id=project_id,
                    statement_a=dc.statement_a,
                    statement_b=dc.statement_b,
                    explanation=dc.explanation,
                    severity=dc.severity,
                    source_ids=dc.source_ids,
                )
            )
        await db.commit()
    return len(detected)


async def _surface_related_research(project_id: str, objective: str) -> None:
    """Search the knowledge base for related prior research (best-effort)."""
    if not settings.knowledge_enabled:
        return
    try:
        related = await knowledge.search(objective, limit=3, exclude_project=project_id)
    except KnowledgeUnavailable:
        return  # embeddings not available; skip silently
    except Exception:
        return
    if related:
        titles = ", ".join(r.title for r in related)
        await _emit(
            project_id, "activity",
            f"Found {len(related)} related prior research project(s): {titles}",
            agent="knowledge", related=[r.project_id for r in related],
        )


async def _index_knowledge(project_id: str) -> None:
    """Index the completed project into the knowledge base (best-effort)."""
    if not settings.knowledge_enabled:
        return
    try:
        n = await knowledge.index_project(project_id)
    except KnowledgeUnavailable:
        return
    except Exception:
        return
    if n:
        await _emit(
            project_id, "activity",
            f"Indexed {n} item(s) into the knowledge base",
            agent="knowledge", indexed=n,
        )


async def _update_knowledge_graph(project_id: str, parent_id: str | None) -> None:
    """Build/update the temporal knowledge graph for a completed run (#7). Best-effort and
    isolated: any failure degrades the graph, never the research (spec §20, §32). Records a
    ``graph_status`` in the existing report_meta (no new column) and emits an activity."""
    if not settings.knowledge_graph_enabled:
        return
    status: dict = {"state": "degraded", "entities": 0, "relationships": 0}
    try:
        status = await kg_graph.build_graph_for_project(project_id)
        if parent_id:
            recon = await kg_graph.reconcile_from_diff(parent_id, project_id)
            status["superseded"] = recon.get("superseded", 0)
            status["disputed"] = recon.get("disputed", 0)
    except Exception as exc:  # noqa: BLE001 - graph must never sink a completed run
        status = {"state": "degraded", "error": type(exc).__name__,
                  "entities": 0, "relationships": 0}

    # Merge into the existing report_meta JSON (no new column).
    try:
        async with _db_lock, SessionLocal() as db:
            proj = await db.get(ResearchProject, project_id)
            if proj is not None:
                meta = dict(proj.report_meta or {})
                meta["graph_status"] = status
                proj.report_meta = meta
                await db.commit()
    except Exception:  # noqa: BLE001
        pass

    if status.get("state") == "ok":
        await _emit(
            project_id, "activity",
            f"Knowledge graph updated — {status.get('entities', 0)} entit(y/ies), "
            f"{status.get('relationships', 0)} relationship(s)",
            agent="knowledge_graph", **{k: v for k, v in status.items() if k != "state"},
        )
    else:
        await _emit(
            project_id, "activity",
            "Knowledge graph update degraded — research is unaffected, retry available",
            agent="knowledge_graph", degraded=True,
        )


async def _build_brief_context(project_id: str) -> str | None:
    """Assemble the structured research brief + typed constraints into a compact planner
    hint (R&D Phase A, spec §6/§9). Deterministic string assembly — zero extra LLM calls.
    Returns None when no brief content exists, so runs without a brief are unaffected."""
    from app.models import Constraint, ResearchBrief

    async with SessionLocal() as db:
        brief = (
            await db.execute(select(ResearchBrief).where(ResearchBrief.project_id == project_id))
        ).scalars().first()
        constraints = (
            await db.execute(select(Constraint).where(Constraint.project_id == project_id))
        ).scalars().all()

    parts: list[str] = []
    if brief:
        if brief.problem_statement:
            parts.append(f"Problem statement: {brief.problem_statement}")
        if brief.background:
            parts.append(f"Background: {brief.background}")
        if brief.expected_outcome:
            parts.append(f"Expected outcome: {brief.expected_outcome}")
        if brief.scope_included:
            parts.append("In scope: " + "; ".join(str(x) for x in brief.scope_included))
        if brief.scope_excluded:
            parts.append("Out of scope (do NOT research): "
                         + "; ".join(str(x) for x in brief.scope_excluded))
        if brief.success_criteria:
            parts.append("Success criteria: " + "; ".join(str(x) for x in brief.success_criteria))
    if constraints:
        parts.append("Constraints: "
                     + "; ".join(f"[{c.ctype}] {c.text}" for c in constraints))
    if not parts:
        return None
    return "=== Research brief (honour scope + constraints) ===\n" + "\n".join(parts)


async def _build_prior_context(parent_id: str):
    """Selective memory of the parent run for a continuation's planner (#4, spec §8).
    Bounded — high-confidence claims, open questions, known contradictions, prior
    recommendation — never the whole report. Returns None if the parent is gone."""
    from app.agents.planner import PriorContext

    async with SessionLocal() as db:
        parent = await db.get(ResearchProject, parent_id)
        if parent is None:
            return None
        claims = (
            await db.execute(select(Claim).where(Claim.project_id == parent_id))
        ).scalars().all()
        questions = (
            await db.execute(
                select(ResearchQuestion).where(ResearchQuestion.project_id == parent_id)
            )
        ).scalars().all()
        gaps = (
            await db.execute(
                select(KnowledgeGap).where(KnowledgeGap.project_id == parent_id)
            )
        ).scalars().all()
        conflicts = (
            await db.execute(select(Conflict).where(Conflict.project_id == parent_id))
        ).scalars().all()
        rec = (
            await db.execute(
                select(Recommendation).where(Recommendation.project_id == parent_id)
            )
        ).scalars().first()
        as_of = (
            parent.completed_at.date().isoformat()
            if parent.completed_at
            else parent.updated_at.date().isoformat()
        )
        objective = parent.objective or parent.query

    important = sorted(
        (
            c
            for c in claims
            if c.status in (ClaimStatus.VERIFIED, ClaimStatus.PARTIALLY_VERIFIED)
        ),
        key=lambda c: c.confidence,
        reverse=True,
    )[: settings.research_again_max_prior_claims]

    open_questions = [q.text for q in questions if not q.answered]
    open_questions += [g.question for g in gaps if not g.resolved]

    contradictions = [
        f"{c.statement_a} vs {c.statement_b}" for c in conflicts
    ]
    contradictions += [
        c.text for c in claims if c.evidence_state == "conflicting"
    ]

    recommendation = None
    if rec and rec.recommended_option:
        recommendation = f"{rec.recommended_option} — {rec.rationale}".strip(" —")

    return PriorContext(
        objective=objective,
        as_of=as_of,
        high_confidence_claims=[c.text for c in important],
        open_questions=open_questions[:12],
        contradictions=contradictions[:8],
        recommendation=recommendation,
    )


async def _build_memory_summary(project_id: str, as_of: str) -> dict:
    """Compact structured memory record built from the finalized rows at completion
    (#4, spec §23). Optimized for future retrieval, not prose. Best-effort."""
    async with SessionLocal() as db:
        proj = await db.get(ResearchProject, project_id)
        claims = (
            await db.execute(select(Claim).where(Claim.project_id == project_id))
        ).scalars().all()
        findings = (
            await db.execute(select(Finding).where(Finding.project_id == project_id))
        ).scalars().all()
        sources = (
            await db.execute(select(Source).where(Source.project_id == project_id))
        ).scalars().all()
        conflicts = (
            await db.execute(select(Conflict).where(Conflict.project_id == project_id))
        ).scalars().all()
        questions = (
            await db.execute(
                select(ResearchQuestion).where(ResearchQuestion.project_id == project_id)
            )
        ).scalars().all()
        gaps = (
            await db.execute(
                select(KnowledgeGap).where(KnowledgeGap.project_id == project_id)
            )
        ).scalars().all()
        rec = (
            await db.execute(
                select(Recommendation).where(Recommendation.project_id == project_id)
            )
        ).scalars().first()
        n_evidence = (
            await db.execute(
                select(ClaimSource).where(
                    ClaimSource.claim_id.in_([c.id for c in claims] or [""])
                )
            )
        ).scalars().all()

    high = sorted(
        (c for c in claims if c.status in (ClaimStatus.VERIFIED, ClaimStatus.PARTIALLY_VERIFIED)),
        key=lambda c: c.confidence, reverse=True,
    )
    weak = [
        c for c in claims
        if c.status in (ClaimStatus.UNVERIFIED, ClaimStatus.INSUFFICIENT_EVIDENCE)
    ]
    conflicting = [c for c in claims if c.evidence_state == "conflicting"]
    avg_conf = round(sum(c.confidence for c in claims) / len(claims), 1) if claims else 0.0
    top_sources = sorted(sources, key=lambda s: s.reliability_score, reverse=True)[:8]

    return {
        "question": proj.query if proj else "",
        "objective": (proj.objective if proj else "") or (proj.query if proj else ""),
        "key_findings": [f.text for f in findings[:8]],
        "high_confidence_claims": [
            {"text": c.text, "confidence": c.confidence} for c in high[:10]
        ],
        "weak_claims": [{"text": c.text, "confidence": c.confidence} for c in weak[:10]],
        "contradictions": [
            {"statement_a": c.statement_a, "statement_b": c.statement_b}
            for c in conflicts
        ],
        "open_questions": [q.text for q in questions if not q.answered]
        + [g.question for g in gaps if not g.resolved],
        "important_sources": [
            {"title": s.title, "url": s.url, "reliability": s.reliability_score}
            for s in top_sources
        ],
        "recommendation": (
            {"option": rec.recommended_option, "confidence": rec.confidence}
            if rec and rec.recommended_option
            else None
        ),
        "counts": {
            "sources": len(sources),
            "claims": len(claims),
            "evidence": len(n_evidence),
        },
        "confidence": {
            "avg": avg_conf,
            "supported": len([c for c in claims if c.status == ClaimStatus.VERIFIED]),
            "weak": len(weak),
            "conflicting": len(conflicting),
        },
        "as_of": as_of,
    }


async def _retry_failed_external(
    project_id, provider, tavily, control, policy, user_id, run_stats, recency_days,
) -> int:
    """Connectivity recovery (#5, spec §26): re-run external tasks that FAILED, but
    only when a fresh probe shows the provider is healthy again. Bounded by
    ``connectivity_max_retries`` (via task ``attempts``); a no-op otherwise so existing
    runs are unaffected. Never restarts the whole run; historical evidence is intact."""
    if not settings.connectivity_enabled or settings.connectivity_max_retries <= 0:
        return 0
    if policy == SourcePolicy.LOCAL_ONLY.value:
        return 0

    async with SessionLocal() as db:
        failed = (
            await db.execute(
                select(ResearchTask).where(
                    ResearchTask.project_id == project_id,
                    ResearchTask.status == TaskStatus.FAILED,
                )
            )
        ).scalars().all()
        eligible = [
            t for t in failed
            if provenance.is_external(t.agent)
            and t.attempts <= settings.connectivity_max_retries
        ]
    if not eligible:
        return 0

    # Only retry if connectivity genuinely recovered.
    snap = await connectivity.manager.snapshot(force=True)
    if not (snap.internet and snap.search_provider):
        return 0

    pending: list[dict] = []
    async with _db_lock, SessionLocal() as db:
        for t in eligible:
            row = await db.get(ResearchTask, t.id)
            if row:
                row.status = TaskStatus.RETRYING
                pending.append({
                    "id": row.id, "question_id": row.question_id,
                    "search_query": row.search_query, "description": row.description,
                    "agent": row.agent,
                })
        await db.commit()

    if run_stats is not None:
        run_stats["retries"] = run_stats.get("retries", 0) + len(pending)
    await _run_tasks(
        project_id, pending, provider, tavily, control,
        base_progress=80, recency_days=recency_days,
        policy=policy, user_id=user_id, run_stats=run_stats,
    )
    # Count how many actually recovered (now COMPLETED).
    async with SessionLocal() as db:
        recovered = (
            await db.execute(
                select(ResearchTask).where(
                    ResearchTask.id.in_([p["id"] for p in pending]),
                    ResearchTask.status == TaskStatus.COMPLETED,
                )
            )
        ).scalars().all()
    return len(recovered)


async def _build_source_health(project_id, snapshot, run_stats) -> dict:
    """Compute the run's source-health summary from the actual persisted sources and
    failed external tasks (#5, spec §22, §23, §40). Only real, counted numbers — no
    invented coverage percentages (§23)."""
    async with SessionLocal() as db:
        sources = (
            await db.execute(select(Source).where(Source.project_id == project_id))
        ).scalars().all()
        tasks = (
            await db.execute(select(ResearchTask).where(ResearchTask.project_id == project_id))
        ).scalars().all()

    # Count live/cached/local by *provenance* (where the evidence came from) so the
    # buckets stay distinct; count stale as a cross-cutting overlay by *freshness*
    # (a source can be "live but stale") — spec §23 lists Stale as its own line.
    live = cached = local = stale = unknown = 0
    for s in sources:
        prov_ = s.provenance
        if prov_ == provenance.LIVE_WEB:
            live += 1
        elif prov_ == provenance.CACHED_WEB:
            cached += 1
        elif prov_ in (provenance.LOCAL_DOCUMENT, provenance.LOCAL_MEMORY, provenance.LOCAL_DATABASE):
            local += 1
        else:
            unknown += 1
        if s.freshness == "stale":
            stale += 1
    unavailable = sum(
        1 for t in tasks
        if t.status == TaskStatus.FAILED and provenance.is_external(t.agent)
    )

    if local and not live and not cached:
        mode = "local"
    elif cached and not live:
        mode = "cache"
    elif live and (cached or local):
        mode = "hybrid"
    elif live:
        mode = "live"
    else:
        mode = "unknown"

    stats = run_stats or {}
    return {
        "live": live,
        "cached": cached,
        "local": local,
        "stale": stale,
        "unknown": unknown,
        "unavailable": unavailable,
        "provider_failures": stats.get("provider_failures", 0),
        "fallback_count": stats.get("fallback", 0),
        "retry_count": stats.get("retries", 0),
        "connectivity_state": snapshot.overall if snapshot else "unknown",
        "research_mode": mode,
        "research_health": provenance.research_health(
            live=live, cached=cached, local=local, unavailable=unavailable
        ),
    }


async def _rd_analysis(project_id, provider) -> str:
    """Run comparison + recommendation + delivery plan; persist Solutions and the
    Recommendation. Returns the recommended option name (or "")."""
    async with SessionLocal() as db:
        proj = await db.get(ResearchProject, project_id)
        claims = (
            await db.execute(select(Claim).where(Claim.project_id == project_id))
        ).scalars().all()
        findings = (
            await db.execute(select(Finding).where(Finding.project_id == project_id))
        ).scalars().all()

    # Zero-evidence run: no claims and no findings were collected (e.g. every external
    # provider failed). Skip R&D entirely rather than let the LLM invent a comparison /
    # recommendation from nothing — a fabricated recommendation must never appear in the
    # report, the Recommendation tab, or the knowledge graph (post-#11 hardening; spec §23.2).
    if not claims and not findings:
        return ""

    result = await rd_analysis.analyse(
        provider,
        objective=proj.objective or proj.query,
        claims=[
            {"text": c.text, "status": c.status.value, "confidence": c.confidence}
            for c in claims
        ],
        findings=[f.text for f in findings],
    )

    async with _db_lock, SessionLocal() as db:
        # Rebuild for idempotency.
        for tbl in (Solution, Recommendation):
            for row in (
                await db.execute(select(tbl).where(tbl.project_id == project_id))
            ).scalars().all():
                await db.delete(row)
        for o in result.options:
            db.add(
                Solution(
                    project_id=project_id,
                    name=o.name,
                    description=o.description,
                    pros=o.pros,
                    cons=o.cons,
                    risks=o.risks,
                    scores=o.scores,
                    is_recommended=o.is_recommended,
                )
            )
        rec = result.recommendation
        if rec:
            db.add(
                Recommendation(
                    project_id=project_id,
                    recommended_option=rec.recommended_option,
                    rationale=rec.rationale,
                    why=rec.why,
                    confidence=rec.confidence,
                    alternatives=rec.alternatives,
                    risks=rec.risks,
                    proof_of_concept=rec.proof_of_concept,
                    roadmap=rec.roadmap,
                )
            )
        await db.commit()
    return result.recommendation.recommended_option if result.recommendation else ""


async def _gap_followup(project_id, provider, round_: int) -> int:
    async with SessionLocal() as db:
        questions = (
            await db.execute(
                select(ResearchQuestion).where(ResearchQuestion.project_id == project_id)
            )
        ).scalars().all()
        findings = (
            await db.execute(select(Finding).where(Finding.project_id == project_id))
        ).scalars().all()

    ev_by_q: dict[str, list[str]] = {}
    q_text_by_id = {q.id: q.text for q in questions}
    for f in findings:
        qt = q_text_by_id.get(f.question_id)
        if qt:
            ev_by_q.setdefault(qt, []).append(f.text)

    gaps = await gap_analysis.find_gaps(
        provider,
        questions=[q.text for q in questions],
        evidence_by_question=ev_by_q,
    )
    if not gaps:
        return 0

    # Persist the detected gaps for visibility (spec §8: identify unanswered questions).
    async with _db_lock, SessionLocal() as db:
        for gap in gaps:
            db.add(
                KnowledgeGap(
                    project_id=project_id,
                    question=gap.question,
                    reason=gap.reason,
                    followup_query=gap.followup_query,
                    round=round_,
                )
            )
        await db.commit()

    # Create a follow-up question + task per gap (respecting the task budget).
    added = 0
    async with _db_lock, SessionLocal() as db:
        existing_tasks = (
            await db.execute(select(ResearchTask).where(ResearchTask.project_id == project_id))
        ).scalars().all()
        remaining = settings.max_research_tasks - len(existing_tasks)
        for gap in gaps:
            if remaining <= 0:
                break
            fq = ResearchQuestion(
                project_id=project_id,
                text=f"[Follow-up] {gap.question}",
                priority=2,
                is_followup=True,
            )
            db.add(fq)
            await db.flush()
            db.add(
                ResearchTask(
                    project_id=project_id,
                    question_id=fq.id,
                    agent="web",
                    description=f"Follow-up: {gap.reason or gap.question}",
                    search_query=gap.followup_query,
                    status=TaskStatus.PENDING,
                    round=round_,
                )
            )
            remaining -= 1
            added += 1
        await db.commit()
    return added


async def _build_report(project_id, provider, source_health: dict | None = None) -> None:
    async with SessionLocal() as db:
        proj = await db.get(ResearchProject, project_id)
        questions = (
            await db.execute(
                select(ResearchQuestion).where(ResearchQuestion.project_id == project_id)
            )
        ).scalars().all()
        findings = (
            await db.execute(select(Finding).where(Finding.project_id == project_id))
        ).scalars().all()
        claims = (
            await db.execute(select(Claim).where(Claim.project_id == project_id))
        ).scalars().all()
        sources = (
            await db.execute(select(Source).where(Source.project_id == project_id))
        ).scalars().all()
        conflicts = (
            await db.execute(select(Conflict).where(Conflict.project_id == project_id))
        ).scalars().all()
        solutions = (
            await db.execute(select(Solution).where(Solution.project_id == project_id))
        ).scalars().all()
        recommendation = (
            await db.execute(
                select(Recommendation).where(Recommendation.project_id == project_id)
            )
        ).scalars().first()

    data = report.ReportInput(
        objective=proj.objective or proj.query,
        query=proj.query,
        questions=[q.text for q in questions],
        findings=[f.text for f in findings],
        claims=[
            {"text": c.text, "status": c.status.value, "confidence": c.confidence}
            for c in claims
        ],
        conflicts=[
            {
                "statement_a": c.statement_a,
                "statement_b": c.statement_b,
                "explanation": c.explanation,
                "severity": c.severity.value,
                "status": c.status.value,
            }
            for c in conflicts
        ],
        solutions=[
            {
                "name": s.name,
                "description": s.description,
                "pros": s.pros,
                "cons": s.cons,
                "risks": s.risks,
                "scores": s.scores,
                "is_recommended": s.is_recommended,
            }
            for s in solutions
        ],
        recommendation=(
            {
                "recommended_option": recommendation.recommended_option,
                "rationale": recommendation.rationale,
                "why": recommendation.why,
                "confidence": recommendation.confidence,
                "alternatives": recommendation.alternatives,
                "risks": recommendation.risks,
                "proof_of_concept": recommendation.proof_of_concept,
                "roadmap": recommendation.roadmap,
            }
            if recommendation
            else None
        ),
        sources=[
            {
                "title": s.title,
                "url": s.url,
                "source_type": s.source_type,
                "reliability_score": s.reliability_score,
                "published_date": s.published_date,
            }
            for s in sorted(sources, key=lambda x: x.reliability_score, reverse=True)
        ],
        mode=proj.mode.value,
        as_of=datetime.now(timezone.utc).date().isoformat(),
        source_health=source_health,
    )
    report_md, meta = await report.generate_report(provider, data)
    if source_health:
        meta["source_health"] = source_health  # surfaced in report_meta (#5)

    async with _db_lock, SessionLocal() as db:
        proj = await db.get(ResearchProject, project_id)
        # Carry any prior-failure history forward: report_meta is fully rebuilt here, so
        # a retry that ultimately succeeds would otherwise lose the record of the failed
        # attempt(s) (spec: never silently erase the original failure).
        prior_history = (proj.report_meta or {}).get("retry_history")
        if prior_history:
            meta["retry_history"] = prior_history
        proj.report_markdown = report_md
        proj.report_meta = meta
        await db.commit()


# --------------------------------------------------------------------------- #
# Small DB utilities
# --------------------------------------------------------------------------- #
async def _mark_task(task_id, status, *, error=None, inc_attempt=False) -> None:
    async with _db_lock, SessionLocal() as db:
        t = await db.get(ResearchTask, task_id)
        if not t:
            return
        t.status = status
        if error:
            t.error = error
        if inc_attempt:
            t.attempts += 1
        await db.commit()


async def _mark_question_answered(question_id) -> None:
    async with _db_lock, SessionLocal() as db:
        q = await db.get(ResearchQuestion, question_id)
        if q:
            q.answered = True
            await db.commit()


async def _question_text(task: dict) -> str:
    if task["question_id"]:
        async with SessionLocal() as db:
            q = await db.get(ResearchQuestion, task["question_id"])
            if q:
                return q.text
    return task["description"]
