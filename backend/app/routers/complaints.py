import uuid
import string
import random
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models.complaint import Complaint, ComplaintMedia
from app.models.work_order import WorkOrder as WorkOrderModel
from app.schemas.complaint import ComplaintResponse, ComplaintTrackResponse, ComplaintListResponse, OTPRequest, OTPVerify
from app.schemas.common import MessageResponse
from app.agents import create_pipeline, PipelineContext
from app.services.media import media_service
from app.services.otp import otp_service
from app.services.email import email_service
from app.services.websocket import ws_manager

router = APIRouter(prefix="/complaints", tags=["complaints"])


def generate_tracking_id() -> str:
    return "CIV-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


async def _run_pipeline_background(
    complaint_id: str,
    tenant_id: Optional[str],
    tracking_id: str,
    raw_input: dict,
):
    """Run the AI pipeline in the background after the response has been sent."""
    db = SessionLocal()
    try:
        pipeline = create_pipeline()
        context = PipelineContext(complaint_id=complaint_id, tenant_id=tenant_id)
        context.raw_input = raw_input
        context.data["tracking_id"] = tracking_id

        result = await pipeline.run(context, db)

        complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
        if not complaint:
            return

        complaint.status = result.status if not result.errors else "submitted"
        complaint.category = result.data.get("category")
        complaint.subcategory = result.data.get("subcategory")
        complaint.priority_score = result.data.get("priority_score")
        complaint.risk_level = result.data.get("risk_level")
        complaint.classification_confidence = result.data.get("classification_confidence")
        complaint.ai_analysis = {
            "structured": result.structured_complaint,
            "classification": result.classification,
            "risk": result.risk_assessment,
            "routing": result.routing,
        }
        complaint.ward = result.data.get("ward") or complaint.ward
        complaint.block = result.data.get("block") or complaint.block
        complaint.district = result.data.get("district") or complaint.district
        complaint.address = result.data.get("address") or complaint.address

        if result.work_order and not result.errors:
            from datetime import datetime
            from app.models.contractor import Contractor
            assigned_contractor_id = result.work_order.get("contractor_id") or result.data.get("recommended_contractor_id")
            wo_status = "assigned" if assigned_contractor_id else "created"
            wo = WorkOrderModel(
                complaint_id=complaint_id,
                tenant_id=tenant_id if tenant_id else None,
                contractor_id=assigned_contractor_id,
                status=wo_status,
                sla_deadline=datetime.fromisoformat(result.work_order["sla_deadline"]) if result.work_order.get("sla_deadline") else None,
                estimated_cost=result.work_order.get("estimated_cost"),
                materials=result.work_order.get("materials"),
                notes=result.work_order.get("summary"),
            )
            db.add(wo)
            if assigned_contractor_id:
                contractor = db.query(Contractor).filter(Contractor.id == assigned_contractor_id).first()
                if contractor:
                    contractor.active_workload = (contractor.active_workload or 0) + 1
                complaint.status = "assigned"

        db.commit()
        print(f"[Pipeline] Completed for {tracking_id} → status={complaint.status} category={complaint.category}")

    except Exception as e:
        import traceback
        print(f"[Pipeline] Error for {tracking_id}: {e}")
        traceback.print_exc()
    finally:
        db.close()


@router.post("/", response_model=ComplaintResponse)
async def submit_complaint(
    background_tasks: BackgroundTasks,
    description: str = Form(...),
    citizen_email: str = Form(...),
    citizen_phone: Optional[str] = Form(None),
    citizen_name: Optional[str] = Form(None),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    address: Optional[str] = Form(None),
    tenant_id: Optional[str] = Form(None),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    tracking_id = generate_tracking_id()
    complaint_id = str(uuid.uuid4())

    # Auto-assign default tenant if none provided
    if not tenant_id:
        from app.models.tenant import Tenant
        default_tenant = db.query(Tenant).first()
        if default_tenant:
            tenant_id = str(default_tenant.id)

    media_files = []
    for f in files:
        saved = await media_service.save_file(f, complaint_id)
        media_files.append(saved)

    complaint = Complaint(
        id=complaint_id,
        tracking_id=tracking_id,
        tenant_id=tenant_id if tenant_id else None,
        citizen_email=citizen_email,
        citizen_phone=citizen_phone,
        citizen_name=citizen_name,
        description=description,
        latitude=latitude,
        longitude=longitude,
        address=address,
        status="submitted",
    )
    db.add(complaint)

    for mf in media_files:
        media = ComplaintMedia(
            complaint_id=complaint_id,
            file_path=mf["file_path"],
            media_type=mf["media_type"],
            original_filename=mf.get("original_filename"),
        )
        db.add(media)

    db.commit()
    db.refresh(complaint)

    # Kick off AI pipeline in background — respond instantly to citizen
    raw_input = {
        "description": description,
        "citizen_email": citizen_email,
        "citizen_phone": citizen_phone,
        "citizen_name": citizen_name,
        "latitude": latitude,
        "longitude": longitude,
        "address": address,
        "media_files": media_files,
    }
    background_tasks.add_task(
        _run_pipeline_background,
        complaint_id,
        tenant_id,
        tracking_id,
        raw_input,
    )

    return complaint


@router.get("/track/{tracking_id}", response_model=ComplaintTrackResponse)
async def track_complaint(tracking_id: str, db: Session = Depends(get_db)):
    from sqlalchemy.orm import joinedload
    complaint = (
        db.query(Complaint)
        .options(joinedload(Complaint.media))
        .filter(Complaint.tracking_id == tracking_id)
        .first()
    )
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return complaint


@router.post("/verify-email")
async def request_otp(data: OTPRequest):
    otp = otp_service.generate_otp(data.email)
    sent = await email_service.send_otp(data.email, otp)
    if not sent:
        # SMTP not configured — return OTP directly for dev/demo use
        print(f"[DEV] OTP for {data.email}: {otp}")
        return {"message": "OTP generated (email not configured)", "dev_otp": otp}
    return {"message": "OTP sent to your email"}


@router.post("/verify-otp")
async def verify_otp(data: OTPVerify):
    if not otp_service.verify_otp(data.email, data.otp):
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")
    from app.utils.auth import create_access_token
    from datetime import timedelta
    token = create_access_token({"sub": data.email, "type": "citizen"}, expires_delta=timedelta(hours=1))
    return {"access_token": token, "token_type": "bearer"}


@router.get("/my", response_model=ComplaintListResponse)
async def my_complaints(email: str, db: Session = Depends(get_db)):
    from sqlalchemy.orm import joinedload
    complaints = (
        db.query(Complaint)
        .options(joinedload(Complaint.media))
        .filter(Complaint.citizen_email == email)
        .order_by(Complaint.created_at.desc())
        .all()
    )
    return ComplaintListResponse(complaints=complaints, total=len(complaints))


@router.post("/{tracking_id}/rate")
async def rate_complaint(tracking_id: str, rating: int, comment: str = "", db: Session = Depends(get_db)):
    """Citizen rates a resolved complaint (1-5 stars). Auto-updates contractor rating."""
    if rating < 1 or rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")
    complaint = db.query(Complaint).filter(Complaint.tracking_id == tracking_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")
    if complaint.status not in ("resolved", "closed", "in_progress"):
        raise HTTPException(status_code=400, detail="Can only rate resolved complaints")
    if complaint.satisfaction_rating is not None:
        raise HTTPException(status_code=400, detail="Already rated")

    complaint.satisfaction_rating = rating
    complaint.satisfaction_comment = comment or None

    # Auto-reopen if rating is very low (1 or 2 stars) — contractor didn't actually fix it
    if rating <= 2 and complaint.status in ("resolved", "closed"):
        complaint.status = "in_progress"
        complaint.reopen_count = (complaint.reopen_count or 0) + 1
        complaint.verified_fixed = False

    # Update contractor rolling rating
    if complaint.work_order and complaint.work_order.contractor_id:
        from app.models.contractor import Contractor
        contractor = db.query(Contractor).filter(Contractor.id == complaint.work_order.contractor_id).first()
        if contractor:
            old_rating = contractor.rating or 0.0
            completed = max(1, contractor.active_workload or 1)
            # simple exponential moving average (alpha=0.3)
            contractor.rating = round(0.7 * old_rating + 0.3 * rating, 2)

    db.commit()
    return {"message": "Thank you for your feedback!", "rating": rating}


@router.post("/{tracking_id}/verify")
async def verify_complaint_fixed(tracking_id: str, is_fixed: bool, db: Session = Depends(get_db)):
    """Citizen confirms whether the issue was actually fixed after it was marked resolved."""
    complaint = db.query(Complaint).filter(Complaint.tracking_id == tracking_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")
    if complaint.status not in ("resolved", "closed"):
        raise HTTPException(status_code=400, detail="Complaint is not in resolved state")

    complaint.verified_fixed = is_fixed
    if not is_fixed:
        # Citizen says it's NOT fixed — auto-reopen
        complaint.status = "in_progress"
        complaint.reopen_count = (complaint.reopen_count or 0) + 1
        db.commit()
        return {"message": "Complaint reopened. We'll follow up with the contractor.", "status": "in_progress"}
    else:
        complaint.status = "closed"
        db.commit()
        return {"message": "Thank you for confirming! Complaint closed.", "status": "closed"}


@router.websocket("/ws/{tracking_id}")
async def complaint_websocket(websocket: WebSocket, tracking_id: str):
    await ws_manager.connect(tracking_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(tracking_id, websocket)
