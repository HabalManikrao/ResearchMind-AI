"""R&D layer Phase F — the reproducibility record.

A single first-class object that aggregates the SAFE, non-secret snapshot needed to reproduce a run
(model/tool/dataset/software/environment identifiers) plus an EXPLICIT reproducibility `verdict`.

Truthfulness is enforced by construction:
- `verdict` defaults to "not_assessed" and is NEVER auto-computed from "fields are populated" — a
  positive verdict requires an explicit assessment (`rationale`/`assessed_by`/`assessed_at`).
- Every metadata field is nullable; an unavailable value stays NULL (never inferred/fabricated —
  e.g. a missing git commit or model version is `None`, not a placeholder).
- It stores IDENTIFIERS only (names/versions/config ids/checksums), never secrets — the API strips
  any credential-looking keys from the free-form `configuration` before persisting.

Versioning is NOT reinvented here: run/object versioning reuses the existing run lineage (#4) and
Dataset versioning (Phase C). This record captures reproducibility metadata + verdict only.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.research import TimestampMixin


def _uuid() -> str:
    return str(uuid.uuid4())


class ReproducibilityRecord(Base, TimestampMixin):
    """One reproducibility snapshot + explicit verdict per project/run (1:1, get-or-create)."""

    __tablename__ = "reproducibility_records"
    __table_args__ = (UniqueConstraint("project_id", name="uq_reproducibility_project"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    # Optional: this record may be about a specific experiment (else it's the run-level snapshot).
    experiment_id: Mapped[str | None] = mapped_column(
        ForeignKey("experiments.id", ondelete="SET NULL"), nullable=True
    )
    dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    dataset_version: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # --- Model / AI (identifiers only — never secrets) --- #
    model_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    embedding_model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # --- Tools / search (identifiers + config id, never keys) --- #
    search_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_config_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    search_date: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # --- Software / environment --- #
    software: Mapped[str | None] = mapped_column(Text, nullable=True)
    software_versions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    hardware: Mapped[str | None] = mapped_column(Text, nullable=True)
    os: Mapped[str | None] = mapped_column(String(200), nullable=True)
    environment: Mapped[str | None] = mapped_column(Text, nullable=True)  # label, not a secret dump
    configuration: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # secret-free
    seed: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # --- Source version control --- #
    git_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    git_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    git_dirty: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # --- Data references (reuse existing storage; no duplication) --- #
    raw_data_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_data_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    as_of: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # --- Explicit verdict (default not_assessed; never auto-computed to a positive value) --- #
    verdict: Mapped[str] = mapped_column(String(30), default="not_assessed")
    rationale: Mapped[str] = mapped_column(Text, default="")
    assessed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    assessed_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Who created/populated the record: agent (auto-capture at completion) | user (manual) | derived.
    origin: Mapped[str] = mapped_column(String(20), default="user")
    notes: Mapped[str] = mapped_column(Text, default="")
