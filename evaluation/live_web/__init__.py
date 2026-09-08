"""Live-web research evaluation (#11).

Measures how well ResearchMind discovers, ranks, diversifies, and verifies information from the
REAL internet, through the EXISTING collection abstraction (no bespoke crawler). Live internet
is non-deterministic, so this is an empirical snapshot — the #9/#10 deterministic suites remain
the regression baseline, and live results never feed back into their fixtures (Phase 9).

Environment note: in a sandbox without a general web search provider, only provider paths that
are actually reachable run (e.g. GitHub); provider-unavailable tasks are recorded as skipped,
never faked as live. Run: ``python -m evaluation.live_web.run_live_eval`` from the repo root.
"""
LIVE_EVAL_SCHEMA_VERSION = "1.0"
