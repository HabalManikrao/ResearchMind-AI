"""Real-world research evaluation (#10).

A reproducible, offline evaluation that compares ResearchMind's evidence pipeline (the REAL
quality engines, composed as the pipeline composes them) against a conventional one-shot LLM
baseline on the SAME realistic fixture corpora — isolating the value of the architecture from
LLM quality (spec §17, §18). It reimplements no engine and makes no network / real-LLM calls.

This measures architecture value on fixtures; it does NOT measure live-web collection quality —
a documented limitation (spec §47). Run: ``python -m evaluation.run_evaluation`` from repo root.
"""
EVALUATION_SCHEMA_VERSION = "1.0"
