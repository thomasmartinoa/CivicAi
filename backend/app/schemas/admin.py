"""Response shapes for the officer endpoints.

These are the contract the frontend codes against, so they are explicit models
rather than dicts: a field renamed here breaks a test instead of a screen.

The officer views carry things the citizen and public views deliberately do not —
the evidence citations, the routing justification, the contractor — because an
officer is accountable for the decision and needs to be able to check it. The public
dashboard's schemas live in `public.py` and are built the other way round, by
exclusion.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TokenUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str | None = None
    role: str
    tenant_id: str | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: TokenUser


class EvidenceCitation(BaseModel):
    """One retrieved chunk, as the officer sees it.

    `citation` is assembled here from source and headers, because
    `RetrievedChunk.citation` is a property and so is absent from the stored JSON —
    see docs/07 §7. The screen should not have to know that.
    """

    node: str
    source: str
    citation: str
    snippet: str | None = None
    score: float | None = None


class WorkOrderSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    sla_hours: int | None = None
    sla_deadline: datetime | None = None
    sla_state: str
    """on_track | warning | urgent | breached | no_deadline, derived from the same
    bands services/sla.py emails on, so the screen and the citizen's inbox cannot
    disagree."""
    estimated_cost: float | None = None
    actual_cost: float | None = None
    cost_basis: str | None = None
    materials: str | None = None
    contractor_id: str | None = None
    contractor_name: str | None = None
    is_cluster: bool = False
    cluster_size: int | None = None
    created_at: datetime
    completed_at: datetime | None = None


class EscalationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_level: str
    to_level: str
    reason: str
    escalated_at: datetime


class ComplaintRow(BaseModel):
    """One line in the officer's queue. Deliberately not the whole complaint: the
    list is read at a glance and a hundred descriptions would make it unreadable."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    tracking_id: str
    status: str
    category: str | None = None
    risk_level: str | None = None
    priority_score: int | None = None
    district: str | None = None
    ward: str | None = None
    classification_confidence: float | None = None
    created_at: datetime
    sla_state: str | None = None
    is_cluster: bool = False


class ComplaintPage(BaseModel):
    items: list[ComplaintRow]
    total: int
    page: int
    size: int
    pages: int


class AdminComplaintDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tracking_id: str
    status: str
    description: str
    terminal_reason: str | None = None
    category: str | None = None
    subcategory: str | None = None
    classification_confidence: float | None = None
    priority_score: int | None = None
    risk_level: str | None = None
    address: str | None = None
    ward: str | None = None
    block: str | None = None
    district: str | None = None
    state: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    citizen_email: str
    citizen_phone: str | None = None
    pipeline_version: str | None = None
    cluster_id: str | None = None
    routing_justification: str | None = None
    email_draft: str | None = None
    email_approved: bool = False
    created_at: datetime
    updated_at: datetime
    media: list[dict] = []
    evidence: list[EvidenceCitation] = []
    work_order: WorkOrderSummary | None = None
    escalations: list[EscalationSummary] = []


class WorkOrderRow(BaseModel):
    """One line in the work-order list: the complaint it belongs to, who has it, and
    how close it is to its deadline."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    complaint_id: str
    tracking_id: str
    category: str | None = None
    risk_level: str | None = None
    status: str
    sla_hours: int | None = None
    sla_deadline: datetime | None = None
    sla_state: str
    contractor_name: str | None = None
    estimated_cost: float | None = None
    is_cluster: bool = False
    cluster_size: int | None = None
    created_at: datetime
    completed_at: datetime | None = None


class WorkOrderPage(BaseModel):
    items: list[WorkOrderRow]
    total: int
    page: int
    size: int
    pages: int


class ContractorRow(BaseModel):
    """A crew, with what they have done. Every per-contractor figure can be None:
    a contractor who has completed nothing has no median resolution time, and
    reporting 0 hours would read as instant work."""

    contractor_id: str
    name: str
    specializations: list[str] = []
    rating: float | None = None
    active_workload: int = 0
    completed: int = 0
    median_hours: float | None = None
    breached: int = 0


class AnalyticsResponse(BaseModel):
    total_complaints: int
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_risk_level: dict[str, int] = {}
    completed_work_orders: int = 0
    median_resolution_hours: float | None = None
    mean_resolution_hours: float | None = None
    fastest_resolution_hours: float | None = None
    slowest_resolution_hours: float | None = None
    sla_measured: int = 0
    sla_met: int = 0
    sla_breached: int = 0
    sla_compliance_rate: float | None = None
    """None when nothing has completed. The frontend must render that as "no data"
    and not as 0%."""


class PerformanceResponse(BaseModel):
    contractors: list[ContractorRow] = []
