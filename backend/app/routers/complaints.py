import uuid
import string
import random
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.database import get_db
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


@router.post("/", response_model=ComplaintResponse)
async def submit_complaint(
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

    try:
        pipeline = create_pipeline()
        context = PipelineContext(complaint_id=str(complaint_id), tenant_id=tenant_id)
        context.raw_input = {
            "description": description,
            "citizen_email": citizen_email,
            "citizen_phone": citizen_phone,
            "citizen_name": citizen_name,
            "latitude": latitude,
            "longitude": longitude,
            "address": address,
            "media_files": media_files,
        }
        context.data["tracking_id"] = tracking_id

        result = await pipeline.run(context, db)

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
        complaint.state = result.data.get("state") or complaint.state
        complaint.address = result.data.get("address") or complaint.address

        if result.work_order and not result.errors:
            from datetime import datetime
            wo = WorkOrderModel(
                complaint_id=complaint_id,
                tenant_id=tenant_id if tenant_id else None,
                contractor_id=result.work_order.get("contractor_id"),
                status="created",
                sla_deadline=datetime.fromisoformat(result.work_order["sla_deadline"]) if result.work_order.get("sla_deadline") else None,
                estimated_cost=result.work_order.get("estimated_cost"),
                materials=result.work_order.get("materials"),
                notes=result.work_order.get("summary"),
            )
            db.add(wo)

        db.commit()
        db.refresh(complaint)

    except Exception as e:
        print(f"Pipeline error: {e}")

    return complaint


@router.get("/track/{tracking_id}")
async def track_complaint(tracking_id: str, db: Session = Depends(get_db)):
    from sqlalchemy.orm import joinedload
    complaint = db.query(Complaint).options(joinedload(Complaint.media), joinedload(Complaint.work_order)).filter(Complaint.tracking_id == tracking_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")
    media_list = [
        {"file_path": m.file_path, "media_type": m.media_type, "original_filename": m.original_filename}
        for m in (complaint.media or [])
    ]
    wo = complaint.work_order
    work_order_data = None
    if wo:
        work_order_data = {
            "id": wo.id, "status": wo.status,
            "sla_deadline": wo.sla_deadline.isoformat() if wo.sla_deadline else None,
            "estimated_cost": wo.estimated_cost, "materials": wo.materials, "notes": wo.notes,
        }
    return {
        "id": complaint.id, "tracking_id": complaint.tracking_id, "status": complaint.status,
        "description": complaint.description, "citizen_email": complaint.citizen_email,
        "citizen_name": complaint.citizen_name, "citizen_phone": complaint.citizen_phone,
        "category": complaint.category, "subcategory": complaint.subcategory,
        "priority_score": complaint.priority_score, "risk_level": complaint.risk_level,
        "address": complaint.address, "ward": complaint.ward, "district": complaint.district,
        "latitude": complaint.latitude, "longitude": complaint.longitude,
        "ai_analysis": complaint.ai_analysis,
        "created_at": complaint.created_at.isoformat() if complaint.created_at else None,
        "updated_at": complaint.updated_at.isoformat() if complaint.updated_at else None,
        "media": media_list,
        "work_order": work_order_data,
    }


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
    complaints = db.query(Complaint).filter(Complaint.citizen_email == email).order_by(Complaint.created_at.desc()).all()
    return ComplaintListResponse(complaints=complaints, total=len(complaints))


@router.websocket("/ws/{tracking_id}")
async def complaint_websocket(websocket: WebSocket, tracking_id: str):
    await ws_manager.connect(tracking_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(tracking_id, websocket)
