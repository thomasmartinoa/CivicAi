"""Importing this package registers every model on Base.metadata.

Alembic autogenerate and Base.metadata.create_all both depend on it, so any new
model module must be added here.
"""

from app.db.models.ai import (
    AgentRun, AgentStep, Document, DocumentChunk, RetrievedChunk,
)
from app.db.models.complaint import Complaint, ComplaintMedia
from app.db.models.core import Contractor, Department, Tenant, User
from app.db.models.evaluation import EvalResult, EvalRun
from app.db.models.workflow import DailyBriefing, Escalation, Notification, WorkOrder

__all__ = [
    "AgentRun", "AgentStep", "Document", "DocumentChunk", "RetrievedChunk",
    "Complaint", "ComplaintMedia",
    "Contractor", "Department", "Tenant", "User",
    "EvalResult", "EvalRun",
    "DailyBriefing", "Escalation", "Notification", "WorkOrder",
]
