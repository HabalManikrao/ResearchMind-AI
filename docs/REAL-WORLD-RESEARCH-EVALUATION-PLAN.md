# Real-World Research Evaluation + Quality Improvement (#10) — Plan

_Written **before** the evaluation harness (spec §3). This milestone does not add features — it
answers empirically: **does ResearchMind's architecture produce more accurate, evidence-backed,
appropriately-confident research than a conventional workflow, and does accumulated knowledge
make later research better?** The correct outcome is the truth, even if it is unflattering
(spec §1, §49, §52)._

---

## 1. Objective

Evaluate ResearchMind under realistic research conditions at the **claim level** (not just final
prose), compare it against a **legitimate conventional baseline**, quantify the **memory →
graph → Research-Again product loop**, classify failures, fix the P0/P1 defects the evaluation
justifies, and report honestly — including where ResearchMind does **not** win.

## 2. What #9 already validates (do not duplicate — spec §2)

#9 is a deterministic unit benchmark of the **pure quality engines** (`score_claim`,
`freshness_state`, `provenance`, `research_diff._classify`, `significance.evaluate`, entity
resolution) against synthetic ground truth: 30/30, all metrics 1.0. It proves each engine
computes correctly **in isolation**.

## 3. What #9 does NOT prove (the #10 gap)

- Whether the engines **composed as a whole pipeline** produce a *useful* research outcome on a
  realistic multi-claim, multi-source task.
- Whether ResearchMind's architecture adds **measurable value over a conventional one-shot LLM
  workflow** on the same evidence (the core product thesis, §54).
- **Claim-level correctness** on realistic tasks (contradiction handling as holistic behavior,
  temporal "historically-true vs currently-true", confidence appropriateness, completeness).
- The **product-value loop** (§33–§36, §53): does memory/graph/Research-Again make research
  #2/#3 more accurate, more complete, less repetitive?

## 4. Honest environment constraint (spec §47) — and the reproducible design

Live-web research requires a Tavily key + a running Ollama and is **non-reproducible**
(changing web content, LLM nondeterminism, source availability). This repo's test environment
is hermetically offline (Ollama pinned to a dead port). Therefore #10 is a **reproducible
fixture-based evaluation**, not a live-web study:

- Each task carries a realistic **corpus** of sources (title/url/reliability/publish-date/
  source-type/**stance**/entailment/excerpt) shaped like real evidence, authored **independently
  of ResearchMind's behavior** (§5).
- **ResearchMind system** = the **real** quality engines composed exactly as the pipeline
  composes them (`verification.score_claim` per candidate claim over its stance-labelled
  evidence, `provenance_of`, `freshness_state`, contradiction detection by stance). The
  quality-bearing computation is the production code, not a re-implementation (spec §29–§31).
- **Baseline system** = the conventional workflow (§17): "search → open top results → one-shot
  LLM synthesis → answer" — accepts every candidate claim as supported at flat confidence,
  cites the first source regardless of stance/entailment, no contradiction detection, no
  provenance, no temporal discrimination.
- Holding **corpus + candidate claims constant**, the only difference is ResearchMind's
  verification/evidence/provenance architecture → a **fair** measurement of the architecture's
  value, isolated from LLM quality (§18). This does **not** claim a better LLM.

**This measures architecture value on fixtures; it does not measure live-web collection
quality.** That is a stated limitation (§47), not a hidden one. LLM-synthesis *prose* is
human-reviewed, not auto-graded (§19).

## 5. Task selection (spec §4, §5) — ~24 tasks, independent ground truth

Categories: current-factual, historical, technical, product-comparison, decision/
recommendation, conflicting-source, rapidly-changing/temporal, policy/regulatory, scientific,
document-grounded, multi-document synthesis, longitudinal (2-run), monitoring/change,
knowledge-graph, follow-up. Tasks require multiple sources / comparison / synthesis /
conflict / temporal reasoning / uncertainty. **Deliberately included**: tasks where
ResearchMind should NOT beat the baseline (a single-authoritative-source fact → tie) so the
result is honest, not rigged (§1, §49).

## 6. Ground truth & annotation schema (spec §7, §8)

Independent (authored from the corpus, not from output). Per evaluated claim:
`claim_text, importance(critical|major|minor), expected_status(SUPPORTED|PARTIALLY_SUPPORTED|
CONTESTED|OUTDATED|UNSUPPORTED|UNKNOWN), supporting_reference_ids, contradicting_reference_ids,
acceptable_variants, temporal_scope`. Per task: `expected_dimensions`, `known_contradictions`,
`expected_recommendation` properties. Citation entailment labelled per (claim, source):
`ENTAILS|PARTIALLY_ENTAILS|DOES_NOT_ENTAIL|IRRELEVANT` (§11).

## 7. Metrics (spec §9–§16)

Claim-weighted (critical=3, major=2, minor=1, §10). **claim_accuracy** (status matches),
**evidence_support**, **citation_correctness** (cited evidence actually entails — not mere
presence, §11), **citation_completeness**, **contradiction_handling** (found both sides +
flagged CONTESTED + no false certainty, §13), **temporal_correctness** (historically-vs-
currently true, §14), **confidence_appropriateness** (calibration ordering: correct-supported >
contested/unsupported, §9), **research_completeness** (dimension coverage, §16),
**recommendation_quality** (requirements/constraints/alternatives/trade-offs/uncertainty, §15;
prose via human review). **provenance_correctness** incl. a **no-false-live** hard gate.

## 8. Baseline comparison (spec §17, §18, §49)

Both systems run on the identical corpus + candidate claims with identical "time budget"
(one pass). The report gives **ResearchMind vs baseline per category**. Expected honest shape:
ResearchMind ≫ baseline on contradiction handling / citation correctness / confidence
calibration / temporal / provenance (baseline has none); ≈ baseline on raw recall of
well-supported claims; **worse on cost** (more evaluation work) — reported as the trade-off
(§38). If ResearchMind does not beat baseline on a category, the report says so (§49).

## 9. Product-value loop (spec §33–§36, §53)

Longitudinal 2-run tasks measured with the **real** `research_diff` + `significance` + graph
resolution: **Research-Again value** (new/corrected claims, changed recommendation, duplicate
reduction), **memory value** (answered-question dedup / continuity), **graph value** (entity
continuity across runs), **monitoring value** (meaningful change detected vs noise suppressed).
Honest rule (§35): a Research-Again that merely repeats run 1 scores low.

## 10. Reproducibility (spec §21)

Deterministic + offline (pins Ollama to a dead port). Results record task id, system version,
engine config, benchmark/eval version → `evaluation/results/latest.json` (git-ignored,
regenerable). `test_evaluation.py` asserts thresholds under pytest so a future regression is
visible (§44).

## 11. Acceptance thresholds (spec §48)

P0 = 0, P1 = 0 (unresolved), security violations = 0, **false-live = 0**. Critical claim
accuracy ≥ 0.9, major ≥ 0.8; citation_correctness ≥ 0.9; contradiction_handling shows no
systematic failure; confidence calibration ordering holds; **ResearchMind ≥ baseline** on
every architecture-differentiated metric (contradiction, citation, confidence, temporal,
provenance) — a strict inequality on at least those where the architecture provides the
capability the baseline lacks. Research-Again shows measurable useful change on longitudinal
tasks; memory/graph value is measured and reported (positive OR "no measurable benefit found",
honestly). No unacceptable performance regression from any fix (§39).

## 12. Failure taxonomy (spec §24) & fix policy (spec §40–§42)

P0 (fabricated evidence / cross-user leak / false-live / corrupted state), P1 (systematic
unsupported claims / missed important contradictions / wrong recommendations / temporal
failures), P2 (retrieval/cost/completeness), P3 (cosmetic). Every P0/P1 → root-cause → minimal
fix → regression test → re-run. Baseline captured **before** any fix (§25).

## 13. Non-goals (spec §28)

No new DB/search-provider/LLM-provider/vector-DB/graph-DB/scheduler/memory/evidence architecture;
no browser/OCR/enterprise/billing; no LLM-only judge as final authority (§19); no gaming the
eval (§1). Live-web quality measurement is explicitly out of scope (documented limitation, §47).

## 14. Deliverables

`evaluation/{tasks/*.json, systems.py, scorer.py, product_value.py, run_evaluation.py}`,
`backend/tests/test_evaluation.py`, `docs/REAL-WORLD-RESEARCH-EVALUATION-REPORT.md`,
`docs/RESEARCH-QUALITY-IMPROVEMENTS.md`, updated `CLAUDE.md` + `GAP-ANALYSIS.md`.
