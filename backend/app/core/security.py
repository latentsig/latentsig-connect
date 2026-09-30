import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.session import get_db


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    raw_id = request.session.get("user_id")
    if not raw_id:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    try:
        user_id = uuid.UUID(raw_id)
    except (ValueError, TypeError):
        request.session.clear()
        raise HTTPException(status_code=401, detail="Sign in to continue.") from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        request.session.clear()
        raise HTTPException(status_code=403, detail="This account is not active.")
    return user


def require_roles(*roles: str):
    allowed = set(roles)

    def authorize(user: User = Depends(current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")
        return user

    return authorize
