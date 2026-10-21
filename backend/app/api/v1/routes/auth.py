from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import current_user
from app.db.models import AuditLog, User
from app.db.session import get_db
from app.core.passwords import verify_password
from app.core.rate_limit import rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])


class EmailLogin(BaseModel):
    email: EmailStr


class PasswordLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


@router.get("/providers")
def providers():
    return {
        "password_login": True,
        "development_email_login": settings.app_env.lower() == "development",
    }


@router.post("/email-login", dependencies=[Depends(rate_limit("auth"))])
def email_login(payload: EmailLogin, request: Request, db: Session = Depends(get_db)):
    if settings.app_env.lower() != "development":
        raise HTTPException(status_code=404, detail="Not found")

    email = str(payload.email).strip().lower()
    if email not in settings.admin_emails:
        raise HTTPException(status_code=403, detail="This email is not on the team access list.")

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            full_name=email.split("@", 1)[0].replace(".", " ").title(),
            role="ADMIN" if email in settings.initial_admins else "SALES",
        )
        db.add(user)
        db.flush()
    elif not user.is_active:
        raise HTTPException(status_code=403, detail="This team account is inactive.")

    request.session.clear()
    request.session["user_id"] = str(user.id)
    db.add(AuditLog(
        user_id=user.id,
        action="admin_login",
        entity_type="user",
        entity_id=str(user.id),
        metadata_json={"provider": "local_allowlist"},
    ))
    db.commit()
    return {"id": str(user.id), "email": user.email, "full_name": user.full_name, "role": user.role}


@router.post("/password-login", dependencies=[Depends(rate_limit("auth"))])
def password_login(payload: PasswordLogin, request: Request, db: Session = Depends(get_db)):
    email = str(payload.email).strip().lower()
    user = db.scalar(select(User).where(User.email == email)) if email in settings.admin_emails else None
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")

    request.session.clear()
    request.session["user_id"] = str(user.id)
    db.add(AuditLog(
        user_id=user.id,
        action="admin_login",
        entity_type="user",
        entity_id=str(user.id),
        metadata_json={"provider": "password"},
    ))
    db.commit()
    return {"id": str(user.id), "email": user.email, "full_name": user.full_name, "role": user.role}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": str(user.id), "email": user.email, "full_name": user.full_name, "role": user.role}


@router.post("/logout")
def logout(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    request.session.clear()
    db.add(AuditLog(user_id=user.id, action="admin_logout", entity_type="user", entity_id=str(user.id), metadata_json={}))
    db.commit()
    return {"ok": True}
