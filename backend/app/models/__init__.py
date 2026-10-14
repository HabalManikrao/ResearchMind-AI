"""SQLAlchemy models. Importing this package registers all mappers on Base."""
from app.models.enums import (
    ClaimStatus,
    ConflictSeverity,
    ConflictStatus,
    DocumentStatus,
    EvidenceStance,
    ProjectStatus,
    ResearchMode,
    TaskStatus,
)
from app.models.analysis import Analysis, Comparison, Conclusion, Limitation
from app.models.brief import Constraint, Objective, ResearchBrief, Terminology
from app.models.cache import CachedSource
from app.models.document import Document, DocumentChunk
from app.models.experiment import Dataset, Experiment, Hypothesis, Method, Result
from app.models.graph import KgClaimLink, KgEntity, KgMention, KgRelationship
from app.models.monitor import MonitorCheck, ResearchMonitor
from app.models.research import (
    AuditLog,
    Claim,
    ClaimSource,
    Conflict,
    Finding,
    KnowledgeGap,
    Recommendation,
    ResearchProject,
    ResearchQuestion,
    ResearchTask,
    Solution,
    Source,
)
from app.models.notification import Notification
from app.models.reproducibility import ReproducibilityRecord
from app.models.schedule import ScheduledResearch
from app.models.user import User

__all__ = [
    "ClaimStatus",
    "ConflictSeverity",
    "ConflictStatus",
    "DocumentStatus",
    "EvidenceStance",
    "ProjectStatus",
    "ResearchMode",
    "TaskStatus",
    "Analysis",
    "AuditLog",
    "CachedSource",
    "Claim",
    "ClaimSource",
    "Comparison",
    "Conclusion",
    "Conflict",
    "Constraint",
    "Dataset",
    "Document",
    "DocumentChunk",
    "Experiment",
    "Finding",
    "Hypothesis",
    "Limitation",
    "Method",
    "Objective",
    "ResearchBrief",
    "Result",
    "Terminology",
    "KgClaimLink",
    "KgEntity",
    "KgMention",
    "KgRelationship",
    "KnowledgeGap",
    "MonitorCheck",
    "Notification",
    "Recommendation",
    "ReproducibilityRecord",
    "ResearchMonitor",
    "ResearchProject",
    "ResearchQuestion",
    "ResearchTask",
    "ScheduledResearch",
    "Solution",
    "Source",
    "User",
]
