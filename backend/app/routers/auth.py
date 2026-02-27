from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.auth import AdminLogin, TokenResponse
from app.utils.auth import verify_password, create_access_token

router = APIRouter(prefix="/admin", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def admin_login(data: AdminLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.role not in ("admin", "officer"):
        raise HTTPException(status_code=403, detail="Not authorized")
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return TokenResponse(access_token=token, role=user.role)
