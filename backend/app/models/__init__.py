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
from app.models.cache import CachedSource
from app.models.document import Document, DocumentChunk
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
    "AuditLog",
    "CachedSource",
    "Claim",
    "ClaimSource",
    "Conflict",
    "Document",
    "DocumentChunk",
    "Finding",
    "KnowledgeGap",
    "MonitorCheck",
    "Notification",
    "Recommendation",
    "ResearchMonitor",
    "ResearchProject",
    "ResearchQuestion",
    "ResearchTask",
    "ScheduledResearch",
    "Solution",
    "Source",
    "User",
]
