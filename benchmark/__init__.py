"""ResearchMind research-quality benchmark (#9).

A reproducible, offline diagnostic that drives ResearchMind's **real** deterministic quality
engines (claim scoring/verification, freshness, provenance, diff classification, monitoring
significance, entity resolution) with machine-readable scenarios carrying ground truth, and
scores the structured outcomes. It reimplements no engine (spec §1, §25) and makes no network
or real-LLM calls (spec §21). Run: ``python -m benchmark.run_benchmark``.
"""
BENCHMARK_SCHEMA_VERSION = "1.0"
