from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.lead import LeadSubmission
from app.services.leads.service import create_lead_submission
from app.core.rate_limit import rate_limit

router = APIRouter(prefix="/leads", tags=["leads"])


@router.post("", status_code=201, dependencies=[Depends(rate_limit("leads"))])
def create_lead(payload: LeadSubmission, db: Session = Depends(get_db)):
    return create_lead_submission(db, payload)
