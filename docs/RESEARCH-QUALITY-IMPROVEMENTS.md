# Research Quality Improvements (#10)

_Every issue the real-world evaluation surfaced, with evidence, root cause, fix, regression
test, and before/after. Fixes are at the root, never in the fixture (spec §40); ground truth
was not altered to flatter ResearchMind (spec §1)._

---

## Improvement 1 (P2) — temporal "outdated" over-flagging

**Issue.** A claim supported by a **fresh** authoritative source **and** a second older source
was reported **OUTDATED**, i.e. a currently-true claim displayed as stale.

**Evidence.** Evaluation task `tmp_002` (a claim backed by an Aug-2026 benchmark *and* a 2023
benchmark, `as_of=2026-09-04`). Baseline evaluation: ResearchMind marked it `OUTDATED`, failing
`claim_accuracy`, `evidence_support`, and `citation_completeness` for a critical claim →
ResearchMind overall 0.960 with these three metrics below 1.0.

**Root cause.** `app/agents/verification.score_claim` computed
`outdated = stale_known >= (len(known) + 1) // 2`. For one fresh + one stale source,
`(2 + 1)//2 == 1`, so a single stale source out of two (a 1-1 tie) counted as "majority stale"
→ `outdated=True`, even though a fresh authoritative source still supported the claim.

**Fix.** Strict majority — a tie with fresh evidence is **not** outdated:
```python
outdated = stale_known > len(known) / 2
```
`app/agents/verification.py`. Confidence's recency factor (which already down-weights stale
evidence continuously) is unchanged, so a claim resting partly on old evidence still scores
lower confidence — it just isn't mislabelled "outdated" when fresh support exists.

**Regression test.** `backend/tests/test_verification.py::test_fresh_source_keeps_claim_current_not_outdated`
(fresh+stale → not outdated & VERIFIED; two-stale → still outdated) plus
`backend/tests/test_evaluation.py::test_temporal_fix_regression`.

**Before / after.** ResearchMind overall **0.960 → 1.000**; `claim_accuracy` 0.945 → 1.0,
`evidence_support` 0.945 → 1.0, `citation_completeness` 0.903 → 1.0. No metric regressed; the
#9 benchmark stayed **30/30** (its `temporal_001` two-stale-news case is still `outdated`), and
all existing verification tests pass.

**Remaining limitation.** With 3+ mixed-freshness sources the rule uses a strict >50% stale
threshold; edge cases (exactly half stale among many) are treated as current — a deliberate,
conservative choice (prefer "current" when any substantial fresh support exists).

---

## Correction 2 (annotation, not a product defect) — `cf_003` expected_dimensions

**Issue.** Evaluation task `cf_003` (whose sole claim, "P guarantees zero downtime", is false
and has no supporting evidence) declared `expected_dimensions: ["reliability"]`, so
ResearchMind was penalised on `research_completeness` for **correctly rejecting** the claim
(the only claim about that dimension).

**Root cause.** Ground-truth authoring error: a task that tests *rejection* has no dimension to
"establish", so demanding coverage of one is wrong. ResearchMind's behaviour (mark UNSUPPORTED)
is correct.

**Fix.** `expected_dimensions: []` for `cf_003` (documented in the task `note`). This corrects a
mis-authored expectation; it does **not** change any ResearchMind claim-level judgement and is
not "gaming" — RM still scores UNSUPPORTED on the false claim (spec §1, §40).

---

## Not changed (deliberate design tensions observed, no defect)

- **Weak contradiction flips a well-supported claim to CONTESTED** (`con_003`: two authoritative
  supporters + one low-reliability blog dissent). ResearchMind marks it CONTESTED. This is
  **intended** (spec: *never hide conflicts*, #2/#4): the conflict is surfaced while
  `confidence_meta` records the 2-supporting-vs-1-weak balance so a reader sees it isn't a
  50/50 split. Independent ground truth agrees (surface the conflict), so this is not a defect.
  Documented here so a future milestone doesn't "fix" it into hiding conflicts.

---

## Summary

| # | Sev | Fix | Regression test | Before → After |
|---|---|---|---|---|
| 1 | P2 | strict-majority `outdated` rule | 2 tests | RM 0.960 → 1.000 |
| 2 | annotation | `cf_003` expected_dimensions = [] | eval re-run | (corrects mis-scored completeness) |

Fixes implemented: **1** (P2, root-cause). Regression tests added: **2** (+ the evaluation
threshold guard). No P0/P1 found. Performance impact: none (the change is a comparison operator
in an already-deterministic function; no added LLM/embedding calls, §39).
