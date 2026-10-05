"""Officer-facing endpoints.

The queue is ordered by priority and then recency, because an officer opens it to
answer "what do I do next" rather than "what happened most recently".

Two things here are not obvious:

- **`sla_state` is derived from `services/sla.py`**, not recomputed. The monitor
  emails a citizen at 50% and 75% of the window; if this screen drew those lines
  anywhere else, an officer would see "on track" for a complaint whose author had
  already been told it was running late.
- **The evidence citations are assembled for the screen.** `RetrievedChunk.citation`
  is a property, so it is not in the stored JSON — only `source` and `headers` are.
  Rebuilding it here means the frontend does not have to know that.
"""

import logging
import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.api.deps import CurrentOfficer
from app.db.base import utcnow
from app.db.models.complaint import Complaint
from app.db.models.core import User
from app.db.session import get_db
from app.schemas.admin import (
    DESCRIPTION_PREVIEW_CHARS, AdminComplaintDetail, AnalyticsResponse, BriefingResponse,
    ComplaintPage, ComplaintRow,
    ComplaintUpdate, WorkOrderUpdate,
    ContractorRow, EmailDraftResponse, EscalationSummary, EvidenceCitation, LoginResponse,
    PerformanceResponse, TokenUser, WorkOrderPage, WorkOrderRow, WorkOrderSummary,
)
from app.services.auth import create_access_token, verify_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

MAX_PAGE_SIZE = 100
"""A tenant can hold a hundred thousand complaints. Without a ceiling, one request
could ask for all of them and serialise the lot."""


class LoginRequest(BaseModel):
    # A plain str, not EmailStr: that needs the email-validator package, and
    # validating the *format* of an address being looked up adds nothing — a
    # malformed one simply will not match a row. It would also hand back a 422
    # distinguishable from the 401 below, which is the oracle this endpoint is
    # careful not to be.
    email: str
    password: str


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> LoginResponse:
    """Exchange a password for a token.

    An unknown email and a wrong password produce the same status and the same
    message. Distinguishing them turns this into an oracle for which addresses have
    accounts, which for a municipal system is a list of its staff. The password is
    also verified even when no user was found, so the two paths take comparable time
    rather than differing by a bcrypt round.
    """
    user = db.query(User).filter(func.lower(User.email) == payload.email.lower()).one_or_none()
    hashed = user.password_hash if user else None
    if not verify_password(payload.password, hashed) or user is None:
        logger.info("failed login for %r", payload.email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Incorrect email or password")
    if user.role not in {"officer", "admin"}:
        # A citizen has no password in practice, but a seeded or imported one might.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="This endpoint requires officer access")

    return LoginResponse(
        access_token=create_access_token(user_id=user.id, role=user.role),
        user=TokenUser.model_validate(user),
    )


@router.get("/me", response_model=TokenUser)
def me(officer: CurrentOfficer) -> TokenUser:
    """Who the token belongs to, so the frontend can restore a session without
    keeping the user in browser storage alongside it."""
    return TokenUser.model_validate(officer)


def _sla_state(work_order) -> str:
    """Translate a work order's position in its window into a word for the screen.

    The thresholds come from services/sla.py so this cannot drift from the emails.
    """
    from app.services.sla import URGENT_AT, WARNING_AT, elapsed_fraction

    if work_order is None or work_order.sla_deadline is None:
        return "no_deadline"
    if work_order.status == "completed":
        return "completed"
    fraction = elapsed_fraction(work_order, utcnow())
    if fraction >= 1.0:
        return "breached"
    if fraction >= URGENT_AT:
        return "urgent"
    if fraction >= WARNING_AT:
        return "warning"
    return "on_track"


@router.get("/complaints", response_model=ComplaintPage)
def list_complaints(
    officer: CurrentOfficer,
    db: Annotated[Session, Depends(get_db)],
    status_: Annotated[str | None, Query(alias="status")] = None,
    category: str | None = None,
    risk_level: str | None = None,
    district: str | None = None,
    q: Annotated[str | None, Query(description="matches the tracking id or description")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 25,
) -> ComplaintPage:
    """The officer's queue, most urgent first.

    Scoped to the officer's own tenant. An officer with no tenant sees nothing rather
    than everything — the same fail-closed rule route_node applies, for the same
    reason: an unscoped query spans every municipality in the database.
    """
    if not officer.tenant_id:
        return ComplaintPage(items=[], total=0, page=page, size=size, pages=0)

    query = db.query(Complaint).filter(Complaint.tenant_id == officer.tenant_id)
    if status_:
        query = query.filter(Complaint.status == status_)
    if category:
        query = query.filter(Complaint.category == category)
    if risk_level:
        query = query.filter(Complaint.risk_level == risk_level)
    if district:
        query = query.filter(Complaint.district == district)
    if q:
        like = f"%{q}%"
        query = query.filter(Complaint.tracking_id.ilike(like) | Complaint.description.ilike(like))

    total = query.order_by(None).count()
    rows = (
        query
        # One query for the work orders rather than one per row: the list is the
        # endpoint most likely to be hit with a large page size.
        .options(selectinload(Complaint.work_order))
        .order_by(Complaint.priority_score.desc().nullslast(), Complaint.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )

    items = []
    for complaint in rows:
        row = ComplaintRow.model_validate(complaint)
        description = complaint.description or ""
        items.append(row.model_copy(update={
            "sla_state": _sla_state(complaint.work_order),
            "is_cluster": bool(complaint.cluster_id),
            # Truncated here rather than in the browser, so a thousand-word
            # description is not sent to render as two lines.
            "description_preview": (
                description[:DESCRIPTION_PREVIEW_CHARS].rstrip() + "…"
                if len(description) > DESCRIPTION_PREVIEW_CHARS else description or None
            ),
        }))
    return ComplaintPage(items=items, total=total, page=page, size=size,
                         pages=math.ceil(total / size) if total else 0)


def _citations(complaint) -> list[EvidenceCitation]:
    citations = []
    for chunk in complaint.evidence or []:
        source = chunk.get("source", "unknown")
        headers = chunk.get("headers") or []
        citations.append(EvidenceCitation(
            node=chunk.get("node", "unknown"),
            source=source,
            citation=" › ".join([source, *headers]),
            snippet=chunk.get("snippet"),
            score=chunk.get("score"),
        ))
    return citations


@router.get("/complaints/{complaint_id}", response_model=AdminComplaintDetail)
def complaint_detail(
    complaint_id: str,
    officer: CurrentOfficer,
    db: Annotated[Session, Depends(get_db)],
) -> AdminComplaintDetail:
    """One complaint, with everything an officer needs to check the decision.

    This is the first screen on which the grounding work from Phase 2b is visible to
    a person: the citations the nodes retrieved and the justification `route` wrote.
    """
    complaint = (
        db.query(Complaint)
        .options(selectinload(Complaint.media), selectinload(Complaint.work_order),
                 selectinload(Complaint.escalations))
        .filter(Complaint.id == complaint_id)
        .one_or_none()
    )
    # 404 rather than 403 for another tenant's complaint: confirming it exists would
    # leak that this id is real somewhere in the system.
    if complaint is None or complaint.tenant_id != officer.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")

    # Assembled field by field rather than model_validate(complaint): the nested
    # work order needs a computed sla_state the ORM object does not carry, and
    # giving that field a default so validation passes would mean a wrong value
    # shipping silently whenever someone forgot to override it.
    nested = {"media", "evidence", "work_order", "escalations"}
    scalars = {name: getattr(complaint, name)
               for name in AdminComplaintDetail.model_fields if name not in nested}

    work_order = None
    if complaint.work_order is not None:
        order = complaint.work_order
        work_order = WorkOrderSummary(
            **{name: getattr(order, name) for name in WorkOrderSummary.model_fields
               if name not in {"sla_state", "contractor_name"}},
            sla_state=_sla_state(order),
            contractor_name=order.contractor.name if order.contractor else None,
        )

    return AdminComplaintDetail(
        **scalars,
        evidence=_citations(complaint),
        work_order=work_order,
        escalations=[EscalationSummary.model_validate(e) for e in complaint.escalations],
        media=[{"file_path": m.file_path, "media_type": m.media_type,
                "original_filename": m.original_filename} for m in complaint.media],
    )


@router.get("/work-orders", response_model=WorkOrderPage)
def list_work_orders(
    officer: CurrentOfficer,
    db: Annotated[Session, Depends(get_db)],
    status_: Annotated[str | None, Query(alias="status")] = None,
    sla_state: Annotated[str | None, Query(description="on_track|warning|urgent|breached")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 25,
) -> WorkOrderPage:
    """Dispatched work, closest to its deadline first.

    `sla_state` is filtered in Python rather than SQL because it depends on "now"
    against each order's own window, which no index can help with. The page is
    capped, so the cost is bounded; a tenant with a hundred thousand orders would
    need the band precomputed on write, and that is a change to make when the number
    hurts rather than before.
    """
    from app.db.models.workflow import WorkOrder

    if not officer.tenant_id:
        return WorkOrderPage(items=[], total=0, page=page, size=size, pages=0)

    query = (db.query(WorkOrder)
             .filter(WorkOrder.tenant_id == officer.tenant_id)
             .options(selectinload(WorkOrder.complaint), selectinload(WorkOrder.contractor)))
    if status_:
        query = query.filter(WorkOrder.status == status_)

    orders = query.order_by(WorkOrder.sla_deadline.asc().nullslast()).all()
    rows = [
        WorkOrderRow(
            id=order.id,
            complaint_id=order.complaint_id,
            tracking_id=order.complaint.tracking_id if order.complaint else "unknown",
            category=order.complaint.category if order.complaint else None,
            risk_level=order.complaint.risk_level if order.complaint else None,
            status=order.status,
            sla_hours=order.sla_hours,
            sla_deadline=order.sla_deadline,
            sla_state=_sla_state(order),
            contractor_name=order.contractor.name if order.contractor else None,
            estimated_cost=order.estimated_cost,
            is_cluster=order.is_cluster,
            cluster_size=order.cluster_size,
            created_at=order.created_at,
            completed_at=order.completed_at,
            completion_photo=order.completion_photo,
        )
        for order in orders
    ]
    if sla_state:
        rows = [r for r in rows if r.sla_state == sla_state]

    total = len(rows)
    start = (page - 1) * size
    return WorkOrderPage(items=rows[start:start + size], total=total, page=page, size=size,
                         pages=math.ceil(total / size) if total else 0)


@router.get("/contractors", response_model=PerformanceResponse)
def list_contractors(
    officer: CurrentOfficer,
    db: Annotated[Session, Depends(get_db)],
) -> PerformanceResponse:
    """Every crew in the tenant, busiest first, including the idle ones — an officer
    choosing who to assign needs to see those most of all."""
    from app.services.analytics import contractor_performance

    if not officer.tenant_id:
        return PerformanceResponse()
    return PerformanceResponse(contractors=[
        ContractorRow(**vars(row))
        for row in contractor_performance(db, tenant_id=officer.tenant_id)
    ])


@router.get("/analytics", response_model=AnalyticsResponse)
def analytics(
    officer: CurrentOfficer,
    db: Annotated[Session, Depends(get_db)],
) -> AnalyticsResponse:
    """The dashboard figures. Every one is computed in services/analytics.py, where
    they are tested against a fixture with known values."""
    from app.services.analytics import complaint_counts, resolution_stats, sla_compliance

    if not officer.tenant_id:
        return AnalyticsResponse(total_complaints=0)

    counts = complaint_counts(db, tenant_id=officer.tenant_id)
    resolution = resolution_stats(db, tenant_id=officer.tenant_id)
    compliance = sla_compliance(db, tenant_id=officer.tenant_id)
    return AnalyticsResponse(
        total_complaints=counts.total,
        by_status=counts.by_status,
        by_category=counts.by_category,
        by_risk_level=counts.by_risk_level,
        completed_work_orders=resolution.completed,
        median_resolution_hours=resolution.median_hours,
        mean_resolution_hours=resolution.mean_hours,
        fastest_resolution_hours=resolution.fastest_hours,
        slowest_resolution_hours=resolution.slowest_hours,
        sla_measured=compliance.measured,
        sla_met=compliance.met,
        sla_breached=compliance.breached,
        sla_compliance_rate=compliance.rate,
    )


@router.get("/analytics/performance", response_model=PerformanceResponse)
def analytics_performance(
    officer: CurrentOfficer,
    db: Annotated[Session, Depends(get_db)],
) -> PerformanceResponse:
    """The same shape as /contractors. The frontend calls both; they are one view of
    the data and keeping them identical is cheaper than explaining a difference."""
    return list_contractors(officer, db)


@router.get("/briefing", response_model=BriefingResponse)
def latest_briefing(
    officer: CurrentOfficer,
    db: Annotated[Session, Depends(get_db)],
) -> BriefingResponse:
    """The most recent briefing for this tenant.

    404 when none has been written yet, rather than an empty narrative: a screen
    showing a blank briefing cannot be told from one showing a quiet day.
    """
    from app.db.models.workflow import DailyBriefing

    briefing = (db.query(DailyBriefing)
                .filter(DailyBriefing.tenant_id == officer.tenant_id)
                .order_by(DailyBriefing.brief_date.desc())
                .first())
    if briefing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No briefing has been generated yet",
        )
    return BriefingResponse.model_validate(briefing)


def _email_draft_chain():
    """The real draft chain. A module-level function so a test can replace it
    without reaching into the service, which has its own tests for the prose."""
    from app.ai.llm import Task, build_structured
    from app.ai.schemas import EmailDraft

    return build_structured(Task.EMAIL_DRAFT, EmailDraft, "email_draft")


def _email_draft_retriever():
    from app.ai.graph.runner import _POLICY_RETRIEVER

    return _POLICY_RETRIEVER


def _owned_complaint(db: Session, complaint_id: str, officer) -> Complaint:
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).one_or_none()
    if complaint is None or complaint.tenant_id != officer.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")
    return complaint


@router.post("/complaints/{complaint_id}/email-draft", response_model=EmailDraftResponse)
def generate_email_draft(
    complaint_id: str,
    officer: CurrentOfficer,
    db: Annotated[Session, Depends(get_db)],
) -> EmailDraftResponse:
    """Draft the department email for this complaint.

    The HTTP half of the flow Phase 2c built and deliberately left unexposed, because
    it was waiting for officer authentication to exist.

    The one endpoint in this phase that calls a model, so the failure modes are
    explicit: a complaint with no category is 409 (there is no department to write
    to yet, which is a state problem and not the caller's fault), and a provider
    outage or a spent quota is 503 with a message saying to try again — never a 500,
    which would tell the officer the system is broken when it is only busy.
    """
    from app.constants import CATEGORY_DEPARTMENT, Category
    from app.services.email_draft import EmailDraftFailed, draft_department_email

    complaint = _owned_complaint(db, complaint_id, officer)
    if not complaint.category:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This complaint has not been classified yet, so there is no "
                   "department to write to",
        )

    # Read what the route needs before the call: draft_department_email closes the
    # session it is handed, which expunges every instance this request is holding.
    # That is its documented contract -- the same warning GraphDeps.session_factory
    # carries -- so nothing ORM-shaped may be kept across the call.
    complaint_id = complaint.id
    tracking_id = complaint.tracking_id
    department = CATEGORY_DEPARTMENT[Category(complaint.category)]

    try:
        draft_department_email(
            complaint_id=complaint_id,
            session_factory=lambda: db,
            chain=_email_draft_chain(),
            retriever=_email_draft_retriever(),
        )
    except EmailDraftFailed as exc:
        logger.warning("email draft unavailable for %s: %s", tracking_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The drafting model is unavailable. Try again in a few minutes.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # Re-queried rather than refreshed: the instance above is detached now.
    stored = db.query(Complaint).filter(Complaint.id == complaint_id).one()
    return EmailDraftResponse(
        complaint_id=stored.id,
        tracking_id=tracking_id,
        department=department,
        draft=stored.email_draft,
        approved=stored.email_approved,
    )


@router.post("/complaints/{complaint_id}/email-draft/approve",
             response_model=EmailDraftResponse)
def approve_email_draft(
    complaint_id: str,
    officer: CurrentOfficer,
    db: Annotated[Session, Depends(get_db)],
) -> EmailDraftResponse:
    """Mark the draft as approved by this officer.

    Idempotent — approving twice is the same as approving once, because a double
    click must not be an error. Refuses an empty draft: approving nothing would set
    a flag that says a human signed off on text that does not exist.
    """
    complaint = _owned_complaint(db, complaint_id, officer)
    if not (complaint.email_draft or "").strip():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="There is no draft to approve. Generate one first.",
        )

    if not complaint.email_approved:
        complaint.email_approved = True
        db.commit()
        logger.info("officer %s approved the email draft for %s",
                    officer.id, complaint.tracking_id)

    return EmailDraftResponse(
        complaint_id=complaint.id,
        tracking_id=complaint.tracking_id,
        draft=complaint.email_draft,
        approved=True,
    )


@router.patch("/complaints/{complaint_id}", response_model=AdminComplaintDetail)
def update_complaint(
    complaint_id: str,
    payload: ComplaintUpdate,
    officer: CurrentOfficer,
    db: Annotated[Session, Depends(get_db)],
) -> AdminComplaintDetail:
    """Move a complaint along its lifecycle, or re-prioritise it.

    **Only the fields an officer is accountable for are writable.** The description,
    the category, the risk score and the routing justification are not: they are the
    record of what the citizen said and what the system decided, and an endpoint that
    let an officer rewrite them would quietly destroy the audit trail that the whole
    citation apparatus exists to produce. Disagreeing with a classification is a
    reason to change the status and say why in `officer_note`, not to edit the past.

    Status changes go through COMPLAINT_TRANSITIONS, so a misdirected PATCH cannot
    drag a rejected complaint back into the queue or mark an unprocessed one resolved.
    """
    from app.constants import COMPLAINT_TRANSITIONS

    complaint = _owned_complaint(db, complaint_id, officer)

    if payload.status is not None and payload.status != complaint.status:
        allowed = COMPLAINT_TRANSITIONS.get(complaint.status, ())
        if payload.status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A complaint that is {complaint.status!r} cannot become "
                       f"{payload.status!r}. Allowed: {', '.join(allowed) or 'nothing'}.",
            )
        previous = complaint.status
        complaint.status = payload.status
        logger.info("officer %s moved %s from %s to %s", officer.id,
                    complaint.tracking_id, previous, payload.status)

        # Work called done that was not is the common case, and the alternative is
        # an officer filing a duplicate. Counting it here is what makes a reopened
        # complaint distinguishable later from one that went right the first time.
        if complaint.status == "in_progress" and previous == "resolved":
            complaint.reopen_count = (complaint.reopen_count or 0) + 1

    db.commit()
    return complaint_detail(complaint_id, officer, db)


@router.post("/complaints/{complaint_id}/approve-email", response_model=EmailDraftResponse)
def approve_email_draft_alias(
    complaint_id: str,
    officer: CurrentOfficer,
    db: Annotated[Session, Depends(get_db)],
) -> EmailDraftResponse:
    """The path the v1-era frontend posts to. Same behaviour as
    /email-draft/approve.

    The frontend also sends an `email_draft` body, which is ignored: approving is a
    signature on the text that is stored, and accepting a body here would let the
    client approve wording the server never saw.
    """
    return approve_email_draft(complaint_id, officer, db)


@router.patch("/work-orders/{work_order_id}", response_model=WorkOrderRow)
def update_work_order(
    work_order_id: str,
    payload: WorkOrderUpdate,
    officer: CurrentOfficer,
    db: Annotated[Session, Depends(get_db)],
) -> WorkOrderRow:
    """Move a work order along, and keep the things that depend on it consistent.

    **`completed_at` is set by the server, never by the client.** Every SLA figure on
    the dashboard is computed from it, so a client-supplied timestamp would let
    anybody with an officer token manufacture a compliance record. The same applies
    to the contractor's workload, which is decremented here rather than trusted from
    the request.
    """
    from app.constants import WORK_ORDER_CLOSED, WORK_ORDER_TRANSITIONS
    from app.db.models.core import Contractor
    from app.db.models.workflow import WorkOrder

    order = (db.query(WorkOrder)
             .options(selectinload(WorkOrder.complaint), selectinload(WorkOrder.contractor))
             .filter(WorkOrder.id == work_order_id).one_or_none())
    if order is None or order.tenant_id != officer.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Work order not found")

    if payload.status is not None and payload.status != order.status:
        allowed = WORK_ORDER_TRANSITIONS.get(order.status, ())
        if payload.status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A work order that is {order.status!r} cannot become "
                       f"{payload.status!r}. Allowed: {', '.join(allowed) or 'nothing'}.",
            )
        was_open = order.status not in WORK_ORDER_CLOSED
        order.status = payload.status

        if payload.status == "completed":
            order.completed_at = utcnow()
        elif payload.status == "in_progress":
            # Reopening clears the completion, or the order would read as finished
            # and in progress at once and the median would count a job twice.
            order.completed_at = None

        # Free the contractor when the order closes, and re-occupy them if it opens
        # again. Guarded by was_open so a repeated PATCH cannot drive the count
        # negative or inflate it.
        if order.contractor_id:
            contractor = db.get(Contractor, order.contractor_id)
            if contractor is not None:
                closing = payload.status in WORK_ORDER_CLOSED
                if was_open and closing:
                    contractor.active_workload = max(0, (contractor.active_workload or 0) - 1)
                elif not was_open and not closing:
                    contractor.active_workload = (contractor.active_workload or 0) + 1

    if payload.actual_cost is not None:
        order.actual_cost = payload.actual_cost
    if payload.notes is not None:
        order.notes = payload.notes
    # Who touched it, on the row rather than only in the log, because the log is
    # not what an officer will be asked to produce six months later.
    order.officer_id = officer.id

    db.commit()
    db.refresh(order)
    return WorkOrderRow(
        id=order.id, complaint_id=order.complaint_id,
        tracking_id=order.complaint.tracking_id if order.complaint else "unknown",
        category=order.complaint.category if order.complaint else None,
        risk_level=order.complaint.risk_level if order.complaint else None,
        status=order.status, sla_hours=order.sla_hours, sla_deadline=order.sla_deadline,
        sla_state=_sla_state(order),
        contractor_name=order.contractor.name if order.contractor else None,
        estimated_cost=order.estimated_cost, is_cluster=order.is_cluster,
        cluster_size=order.cluster_size, created_at=order.created_at,
        completed_at=order.completed_at, completion_photo=order.completion_photo,
    )
