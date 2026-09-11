"""Citizen-facing complaint endpoints.

The handler persists the complaint and returns immediately; the graph runs in
the background. v1 made the same call and it was right — AI calls take seconds
and a citizen should not wait for them. What v1 lacked was durability, which
Phase 1b's checkpointer and this phase's resume sweep supply.
"""

import secrets
import string
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.models.complaint import Complaint, ComplaintMedia
from app.db.session import get_db
from app.schemas.complaint import ComplaintDetail, ComplaintSubmitted
from app.services.execution import schedule_complaint_run
from app.services.media import MediaTooLarge, MediaTypeNotAllowed, store_upload
from app.services.tenancy import NoTenantConfigured, resolve_tenant_id

router = APIRouter(prefix="/complaints", tags=["complaints"])

_ALPHABET = string.ascii_uppercase + string.digits
MIN_DESCRIPTION = 10


def generate_tracking_id() -> str:
    """Random, not sequential: a tracking id is the only credential for reading
    a complaint, so it must not be guessable from a neighbouring one."""
    return "CIV-" + "".join(secrets.choice(_ALPHABET) for _ in range(8))


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=ComplaintSubmitted)
async def submit_complaint(
    description: Annotated[str, Form(min_length=MIN_DESCRIPTION)],
    citizen_email: Annotated[str, Form()],
    citizen_name: Annotated[str | None, Form()] = None,
    citizen_phone: Annotated[str | None, Form()] = None,
    latitude: Annotated[float | None, Form()] = None,
    longitude: Annotated[float | None, Form()] = None,
    address: Annotated[str | None, Form()] = None,
    tenant_id: Annotated[str | None, Form()] = None,
    files: Annotated[list[UploadFile], File()] = [],
    db: Session = Depends(get_db),
) -> Complaint:
    # resolve_tenant_id's `if requested:` check treats "" the same as "not
    # provided" by accident (Task 1 review). A multipart form readily sends
    # tenant_id="" for a field the citizen never filled in, so normalise that
    # here, deliberately, to the same None that an omitted field would carry —
    # rather than lean on the callee's truthiness quirk to get there.
    if tenant_id == "":
        tenant_id = None

    try:
        resolved_tenant = resolve_tenant_id(db, tenant_id)
    except NoTenantConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stored = []
    for upload in files:
        try:
            stored.append(store_upload(await upload.read(), upload.filename or "upload"))
        except (MediaTypeNotAllowed, MediaTooLarge) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    complaint = Complaint(
        tracking_id=generate_tracking_id(),
        tenant_id=resolved_tenant,
        citizen_email=citizen_email,
        citizen_name=citizen_name,
        citizen_phone=citizen_phone,
        description=description,
        latitude=latitude,
        longitude=longitude,
        address=address,
        status="submitted",
    )
    db.add(complaint)
    db.flush()
    for item in stored:
        db.add(ComplaintMedia(
            complaint_id=complaint.id,
            file_path=item.file_path,
            media_type=item.media_type,
            original_filename=item.original_filename,
        ))
    db.commit()
    db.refresh(complaint)

    schedule_complaint_run(complaint.id)
    return complaint


@router.get("/track/{tracking_id}", response_model=ComplaintDetail)
async def track_complaint(tracking_id: str, db: Session = Depends(get_db)) -> Complaint:
    complaint = (
        db.query(Complaint).filter(Complaint.tracking_id == tracking_id).one_or_none()
    )
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return complaint
