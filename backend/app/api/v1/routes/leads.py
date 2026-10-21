import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.lead import LeadSubmission
from app.services.leads.service import create_lead_submission
from app.core.rate_limit import rate_limit

router = APIRouter(prefix="/leads", tags=["leads"])


@router.post("", status_code=201, dependencies=[Depends(rate_limit("leads"))])
def create_lead(payload: LeadSubmission, db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=36)):
    if idempotency_key:
        try:
            idempotency_key = str(uuid.UUID(idempotency_key))
        except ValueError:
            raise HTTPException(status_code=400, detail="Idempotency-Key must be a UUID.") from None
    return create_lead_submission(db, payload, idempotency_key)
