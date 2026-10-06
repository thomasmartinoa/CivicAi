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


DESCRIPTION_PREVIEW_CHARS = 280


class ComplaintRow(BaseModel):
    """One line in the officer's queue. Deliberately not the whole complaint: the
    list is read at a glance and a hundred descriptions would make it unreadable.

    `description_preview` is the one exception, because an officer triaging a queue
    needs to see what the citizen actually said and a category alone does not tell
    them. It is truncated — the detail endpoint carries the full text. This is the
    authenticated surface, so unlike the public dashboard there is no reason to
    withhold it.
    """

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
    description_preview: str | None = None


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
    completion_photo: str | None = None
    """The proof-of-work image, if one was ever attached. Published on the officer
    surface because officers are authenticated; the public dashboard withholds all
    media. Nothing writes this yet — the upload endpoint is deferred — so it is
    null in practice and the officer screen must not gate completion on it."""


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


class BriefingResponse(BaseModel):
    """The officer's morning briefing.

    `is_fallback` is in the response, not just the table. v1's briefing served
    template text for the life of the project because nothing surfaced that the
    model had never run — the flag has to reach the screen or it may as well not
    exist.
    """

    model_config = ConfigDict(from_attributes=True)

    brief_date: datetime
    narrative: str
    is_fallback: bool
    new_complaints: int = 0
    resolved_today: int = 0
    sla_at_risk: int = 0
    escalations_today: int = 0
    clusters_detected: int = 0
    created_at: datetime


class EmailDraftResponse(BaseModel):
    complaint_id: str
    tracking_id: str
    department: str | None = None
    draft: str | None = None
    approved: bool = False


class ComplaintUpdate(BaseModel):
    """What an officer may change about a complaint: where it is in its lifecycle,
    and nothing else.

    Not writable, on purpose: `description` (what the citizen said), `category`,
    `risk_level`, `priority_score` and `routing_justification` (what the system
    decided and cited). An endpoint that let an officer rewrite those would quietly
    destroy the audit trail the whole citation apparatus exists to produce.
    Disagreeing with a classification is a reason to change the status, not to edit
    the past.

    There is also no officer-note field, because the table has no column for one —
    recording *why* a status changed needs a migration, and it is written down as
    carried forward rather than smuggled into an existing column.
    """

    status: str | None = None


class WorkOrderUpdate(BaseModel):
    """What an officer may change about a work order.

    `completed_at` is absent deliberately — the server sets it. Every SLA figure on
    the dashboard is computed from that timestamp, so accepting it from a client
    would let anybody with an officer token manufacture a compliance record.
    """

    status: str | None = None
    actual_cost: float | None = None
    notes: str | None = None


class AgentStepRow(BaseModel):
    """One step in a run's timeline.

    `status` carries `step_limit` for a chat turn the agent gave up on. That value
    exists so a trace viewer can show a surrender as a surrender — rendered as
    `completed`, an agent that ran out of steps looks like one that finished.
    """

    model_config = ConfigDict(from_attributes=True)

    seq: int
    node: str
    status: str
    duration_ms: int | None = None
    tokens: int | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    error: str | None = None
    created_at: datetime


class AgentRunRow(BaseModel):
    """A run, with enough to list it without loading its steps."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    complaint_id: str | None = None
    tracking_id: str | None = None
    """None for a chat run, which belongs to no single complaint."""
    kind: str
    """`pipeline` or `chat`, derived from whether a complaint is named. A caller
    should not have to know that `complaint_id IS NULL` means a conversation."""
    thread_id: str
    status: str
    graph_version: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error: str | None = None
    step_count: int = 0
    label: str | None = None
    """What this run was about, for a list that would otherwise be a column of
    identical rows. A pipeline run is identified by its tracking id; a chat run has
    no tracking id, so this carries the opening question instead."""


class AgentRunDetail(AgentRunRow):
    steps: list[AgentStepRow] = []


class AgentRunPage(BaseModel):
    items: list[AgentRunRow]
    total: int
    page: int
    size: int
    pages: int
