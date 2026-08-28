"""Stateful research orchestration (custom, DB-persisted).

Chosen over LangGraph for the lean-local MVP: state lives in SQLite so a run
survives restart/pause/failure (spec §19), with fewer moving parts. The pipeline
stages are explicit and can be ported to a graph engine later.
"""
