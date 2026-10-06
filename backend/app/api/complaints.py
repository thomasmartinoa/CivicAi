"""Citizen-facing complaint endpoints.

The handler persists the complaint and returns immediately; the graph runs in
the background. v1 made the same call and it was right — AI calls take seconds
and a citizen should not wait for them. What v1 lacked was durability, which
Phase 1b's checkpointer and this phase's resume sweep supply.
"""

import logging
import secrets
import string
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.config import settings
from app.api.deps import VerifiedCitizen
from app.db.models.complaint import Complaint, ComplaintMedia
from app.db.session import get_db
from app.schemas.complaint import (
    ComplaintDetail, ComplaintSubmitted, OtpRequest, OtpRequested, OtpVerification,
    VerifiedComplaints,
)
from app.services import media as media_module
from app.services.auth import create_citizen_token
from app.services.execution import schedule_complaint_run
from app.services.media import (
    MAX_UPLOAD_BYTES, MediaTooLarge, MediaTypeNotAllowed, StoredMedia, store_upload,
)
from app.services.tenancy import NoTenantConfigured, resolve_tenant_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/complaints", tags=["complaints"])

_ALPHABET = string.ascii_uppercase + string.digits
_CHUNK = 64 * 1024
MIN_DESCRIPTION = 10


def generate_tracking_id() -> str:
    """Random, not sequential: a tracking id is the only credential for reading
    a complaint, so it must not be guessable from a neighbouring one."""
    return "CIV-" + "".join(secrets.choice(_ALPHABET) for _ in range(8))


async def _read_bounded(upload: UploadFile, limit: int) -> bytes:
    """Read at most `limit` bytes, then stop.

    `await upload.read()` with no argument buffers the whole body before
    store_upload can reject it on size — which on a public endpoint means a
    client chooses how much memory we allocate.
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(_CHUNK):
        total += len(chunk)
        if total > limit:
            raise MediaTooLarge(f"upload exceeds the {limit} byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


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

    stored: list[StoredMedia] = []
    try:
        for upload in files:
            data = await _read_bounded(upload, MAX_UPLOAD_BYTES)
            stored.append(store_upload(data, upload.filename or "upload"))
    except (MediaTypeNotAllowed, MediaTooLarge) as exc:
        # Files accepted earlier in this batch are already on disk and no
        # complaint will reference them. Remove them rather than leaking.
        for item in stored:
            (media_module.UPLOAD_ROOT / Path(item.file_path).name).unlink(missing_ok=True)
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


@router.websocket("/ws/{tracking_id}")
async def complaint_updates(websocket: WebSocket, tracking_id: str) -> None:
    from app.services.streaming import registry

    await websocket.accept()
    registry.connect(tracking_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        # Every exit path deregisters, not only the clean one. A transport
        # error or a cancellation at shutdown must not leave a subscriber
        # behind — the registry only prunes dead sockets when it next
        # publishes, and a finished complaint never publishes again.
        registry.disconnect(tracking_id, websocket)


# ── citizen self-service: email and OTP ─────────────────────────────────────
#
# A citizen has no account. The only thing tying them to a complaint is the email
# address they filed it under, so reading their own history means proving they
# control that address. Everything in app/services/otp.py is about the ways that
# could leak; these two routes exist to not add any more.


@router.post("/verify-email", response_model=OtpRequested)
def request_otp(payload: OtpRequest, db: Annotated[Session, Depends(get_db)]) -> OtpRequested:
    """Email a one-time code to the address, if it has complaints.

    **The response is identical whether or not it does.** Telling the caller would
    turn this into a way to ask "has this person complained?", which for a
    municipality is a question about somebody's dealings with the state. Nothing is
    sent to an address with no complaints, and the caller cannot tell.

    Rate limiting also answers identically: a caller who has exhausted their codes
    learns nothing, and the citizen's inbox is protected either way.
    """
    from app.services.notify import _send_email
    from app.services.otp import OtpRateLimited, complaints_for, issue_code

    same_answer = OtpRequested(
        message="If that address has complaints, a code is on its way. It expires in "
                f"{settings.otp_expire_minutes} minutes."
    )

    if not complaints_for(db, payload.email):
        logger.info("OTP requested for an address with no complaints")
        return same_answer

    try:
        issued = issue_code(db, payload.email)
    except OtpRateLimited:
        logger.info("OTP request refused by the rate limit")
        return same_answer

    try:
        _send_email(
            payload.email.strip().lower(),
            "CivicAI — your verification code",
            f"Your code is {issued.code}. It expires in "
            f"{settings.otp_expire_minutes} minutes.\n\n"
            "If you did not ask for this, you can ignore it.",
        )
    except Exception:
        # The code is already issued and usable; a dead SMTP relay is an operational
        # problem, not a reason to tell the caller anything different.
        logger.warning("could not send an OTP email", exc_info=True)

    return same_answer


@router.post("/verify-otp", response_model=VerifiedComplaints)
def verify_otp(
    payload: OtpVerification,
    db: Annotated[Session, Depends(get_db)],
) -> VerifiedComplaints:
    """Exchange a correct code for that address's complaints.

    A wrong code and an address that was never sent one give the same 401, for the
    same reason the request endpoint gives one answer.
    """
    from app.services.otp import complaints_for, verify_code

    if not verify_code(db, payload.email, payload.code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="That code is not valid")

    address = payload.email.strip().lower()
    complaints = complaints_for(db, address)
    # A token, not just the data: the frontend's next call is /complaints/my, and
    # without something to present there it would have to send the address again and
    # be believed. See that route's docstring.
    return VerifiedComplaints(
        email=address,
        access_token=create_citizen_token(address),
        complaints=[ComplaintDetail.model_validate(c) for c in complaints],
    )


@router.get("/my", response_model=list[ComplaintDetail])
def my_complaints(
    citizen: VerifiedCitizen,
    db: Annotated[Session, Depends(get_db)],
    email: str | None = None,
) -> list[ComplaintDetail]:
    """The complaints belonging to the verified token holder.

    **The `email` query parameter is accepted and ignored.** The v1-era frontend calls
    this as `/complaints/my?email=<address>` and that signature is the whole OTP flow
    undone: anyone could read anybody's complaints by guessing an address, which is
    exactly what the one-time code exists to prevent. Rather than break the frontend
    or honour the parameter, the address comes from the token and the parameter is
    discarded — there is a test that passes somebody else's address and gets the
    caller's own complaints back.
    """
    from app.services.otp import complaints_for

    if email and email.strip().lower() != citizen:
        logger.info("a /complaints/my call passed an address other than its token's")
    return [ComplaintDetail.model_validate(c) for c in complaints_for(db, citizen)]
