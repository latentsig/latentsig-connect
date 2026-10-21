import io
import uuid
from datetime import date, datetime, time, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import current_user, require_roles
from app.db.models import AuditLog, BusinessCard, Event, IntegrationJob, Interaction, Lead, LeadNote, User
from app.db.session import get_db
from app.services.storage.business_cards import storage

router = APIRouter(prefix="/admin", tags=["admin"])
STATUSES = {"new", "contacted", "qualified", "meeting", "proposal", "won", "follow_up_later", "not_interested", "lost"}
ROLES = {"ADMIN", "MANAGER", "SALES", "VIEWER"}


class LeadUpdate(BaseModel):
    status: str | None = None
    assigned_to: uuid.UUID | None = None


class NoteInput(BaseModel):
    note: str = Field(min_length=1, max_length=5000)
    interaction_id: uuid.UUID | None = None


class BulkAssignInput(BaseModel):
    lead_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    assigned_to: uuid.UUID | None = None


class UserUpdate(BaseModel):
    full_name: str = Field(min_length=1, max_length=180)
    role: Literal["ADMIN", "MANAGER", "SALES", "VIEWER"]
    is_active: bool = True


class EventInput(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    start_date: date | None = None
    end_date: date | None = None
    location: str | None = Field(default=None, max_length=180)
    is_active: bool = True


def _latest_interaction():
    latest = select(Interaction.lead_id.label("lead_id"), func.max(Interaction.created_at).label("created_at")).group_by(Interaction.lead_id).subquery()
    return select(Lead, Interaction).join(latest, latest.c.lead_id == Lead.id).join(
        Interaction, (Interaction.lead_id == Lead.id) & (Interaction.created_at == latest.c.created_at)
    )


def _lead_row(lead: Lead, interaction: Interaction, db: Session) -> dict:
    event = db.get(Event, interaction.event_id) if interaction.event_id else None
    assignee = db.get(User, interaction.assigned_to) if interaction.assigned_to else None
    business_card = db.scalar(select(BusinessCard).where(BusinessCard.interaction_id == interaction.id))
    return {
        "id": str(lead.id), "lead_code": lead.lead_code, "full_name": lead.full_name,
        "company": lead.company, "job_title": lead.job_title, "email": lead.email,
        "email_type": lead.email_type, "phone": lead.phone, "normalized_phone": lead.normalized_phone, "country": lead.country,
        "website": lead.website, "address": lead.address, "created_at": lead.created_at.isoformat(), "updated_at": lead.updated_at.isoformat(),
        "interaction": {
            "id": str(interaction.id), "event_id": str(interaction.event_id) if interaction.event_id else None,
            "event": event.name if event else None, "event_slug": event.slug if event else None,
            "interest": interaction.interest, "intent": interaction.intent,
            "other_interest_details": interaction.other_interest_details,
            "other_intent_details": interaction.other_intent_details,
            "requirement_message": interaction.requirement_message, "capture_method": interaction.capture_method,
            "data_processing_consent_at": interaction.data_processing_consent_at.isoformat() if interaction.data_processing_consent_at else None,
            "follow_up_consent_at": interaction.follow_up_consent_at.isoformat() if interaction.follow_up_consent_at else None,
            "consent_notice_version": interaction.consent_notice_version,
            "ai_processing_consent_at": interaction.ai_processing_consent_at.isoformat() if interaction.ai_processing_consent_at else None,
            "ai_processing_consent_notice_version": interaction.ai_processing_consent_notice_version,
            "business_card": {"has_back": bool(business_card.back_storage_path)} if business_card else None,
            "source": interaction.source, "captured_by": interaction.captured_by,
            "utm_source": interaction.utm_source, "utm_medium": interaction.utm_medium,
            "utm_campaign": interaction.utm_campaign, "status": interaction.status,
            "assigned_to": str(assignee.id) if assignee else None,
            "assigned_name": assignee.full_name if assignee else None,
            "created_at": interaction.created_at.isoformat(),
        },
    }


def _filter_query(query, search, event, status, interest, intent, captured_by, assigned_to, capture_method, date_from, date_to, user):
    if user.role == "SALES":
        # Sales can see their assigned work plus the shared, unassigned intake queue.
        # Mutations remain restricted to leads assigned to the current salesperson.
        query = query.where(or_(Interaction.assigned_to == user.id, Interaction.assigned_to.is_(None)))
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(Lead.full_name.ilike(term), Lead.company.ilike(term), Lead.email.ilike(term), Lead.phone.ilike(term), Lead.lead_code.ilike(term)))
    if event:
        query = query.join(Event, Event.id == Interaction.event_id).where(Event.slug == event)
    if status:
        query = query.where(Interaction.status == status)
    if interest:
        query = query.where(cast(Interaction.interest, String).ilike(f"%{interest}%"))
    if intent:
        query = query.where(Interaction.intent == intent)
    if captured_by:
        query = query.where(Interaction.captured_by.ilike(f"%{captured_by}%"))
    if assigned_to:
        query = query.where(Interaction.assigned_to == assigned_to)
    if capture_method:
        query = query.where(Interaction.capture_method == capture_method)
    if date_from:
        query = query.where(Interaction.created_at >= datetime.combine(date_from, time.min, timezone.utc))
    if date_to:
        query = query.where(Interaction.created_at < datetime.combine(date_to.fromordinal(date_to.toordinal() + 1), time.min, timezone.utc))
    return query


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(current_user)):
    query = _latest_interaction()
    if user.role == "SALES":
        query = query.where(or_(Interaction.assigned_to == user.id, Interaction.assigned_to.is_(None)))
    rows = db.execute(query).all()
    by_status: dict[str, int] = {status: 0 for status in STATUSES}
    by_interest: dict[str, int] = {}
    by_employee: dict[str, int] = {}
    by_date: dict[str, int] = {}
    by_capture: dict[str, int] = {}
    by_event: dict[str, int] = {}
    for lead, interaction in rows:
        by_status[interaction.status] = by_status.get(interaction.status, 0) + 1
        for item in interaction.interest:
            by_interest[item] = by_interest.get(item, 0) + 1
        employee = interaction.captured_by or "Unattributed"
        by_employee[employee] = by_employee.get(employee, 0) + 1
        by_date[interaction.created_at.date().isoformat()] = by_date.get(interaction.created_at.date().isoformat(), 0) + 1
        by_capture[interaction.capture_method] = by_capture.get(interaction.capture_method, 0) + 1
        event = db.get(Event, interaction.event_id) if interaction.event_id else None
        event_name = event.name if event else "No event"
        by_event[event_name] = by_event.get(event_name, 0) + 1
    return {
        "total_leads": len(rows), "by_status": by_status,
        "by_interest": by_interest, "by_employee": by_employee,
        "by_date": dict(sorted(by_date.items())), "by_capture_method": by_capture,
        "by_event": by_event,
    }


@router.get("/leads")
def list_leads(
    search: str | None = None, event: str | None = None, status: str | None = None,
    interest: str | None = None, intent: str | None = None, captured_by: str | None = None,
    assigned_to: uuid.UUID | None = None, capture_method: str | None = None,
    date_from: date | None = None, date_to: date | None = None,
    sort_by: str = Query("created_at"), sort_order: Literal["asc", "desc"] = Query("desc"),
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    query = _filter_query(_latest_interaction(), search, event, status, interest, intent, captured_by, assigned_to, capture_method, date_from, date_to, user)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    sort_columns = {
        "created_at": Interaction.created_at, "full_name": Lead.full_name,
        "company": Lead.company, "status": Interaction.status,
        "capture_method": Interaction.capture_method, "captured_by": Interaction.captured_by,
    }
    if sort_by == "event":
        if not event:
            query = query.outerjoin(Event, Interaction.event_id == Event.id)
        sort_column = Event.name
    else:
        sort_column = sort_columns.get(sort_by)
    if sort_column is None:
        raise HTTPException(status_code=422, detail="Choose a supported lead sort column.")
    order = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    rows = db.execute(query.order_by(order, Lead.id.asc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_lead_row(lead, interaction, db) for lead, interaction in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/leads/bulk-assign")
def bulk_assign_leads(payload: BulkAssignInput, db: Session = Depends(get_db), user: User = Depends(require_roles("ADMIN", "MANAGER"))):
    lead_ids = list(dict.fromkeys(payload.lead_ids))
    leads = db.scalars(select(Lead).where(Lead.id.in_(lead_ids))).all()
    if len(leads) != len(lead_ids):
        raise HTTPException(status_code=404, detail="One or more selected leads could not be found.")
    assignee = db.get(User, payload.assigned_to) if payload.assigned_to else None
    if payload.assigned_to and (assignee is None or not assignee.is_active):
        raise HTTPException(status_code=422, detail="Choose an active team member.")
    for lead in leads:
        interaction = db.scalar(select(Interaction).where(Interaction.lead_id == lead.id).order_by(Interaction.created_at.desc(), Interaction.id.desc()).limit(1))
        if interaction is None:
            raise HTTPException(status_code=404, detail="A selected lead has no interaction to assign.")
        interaction.assigned_to = assignee.id if assignee else None
        db.add(AuditLog(user_id=user.id, action="lead_assigned", entity_type="lead", entity_id=str(lead.id), metadata_json={"assigned_to": str(assignee.id) if assignee else None, "bulk": True}))
        if settings.google_sheet_id:
            db.add(IntegrationJob(type="google_sheets_upsert", entity_id=interaction.id, status="pending"))
    db.commit()
    return {"updated": len(leads)}


@router.get("/leads/{lead_id}")
def lead_detail(lead_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found.")
    interactions = db.scalars(select(Interaction).where(Interaction.lead_id == lead.id).order_by(Interaction.created_at.desc())).all()
    if user.role == "SALES" and not any(item.assigned_to == user.id for item in interactions):
        if not interactions or interactions[0].assigned_to is not None:
            raise HTTPException(status_code=404, detail="Lead not found.")
    if user.role == "SALES":
        interactions = [item for item in interactions if item.assigned_to is None or item.assigned_to == user.id]
    history = []
    for item in interactions:
        row = _lead_row(lead, item, db)["interaction"]
        card = db.scalar(select(BusinessCard).where(BusinessCard.interaction_id == item.id))
        row["business_card"] = {"filename": card.original_filename, "mime_type": card.mime_type, "back_filename": card.back_original_filename, "has_back": bool(card.back_storage_path)} if card else None
        history.append(row)
    notes = db.scalars(select(LeadNote).where(LeadNote.lead_id == lead.id).order_by(LeadNote.created_at.desc())).all()
    return {
        "id": str(lead.id), "lead_code": lead.lead_code, "full_name": lead.full_name,
        "company": lead.company, "job_title": lead.job_title, "email": lead.email,
        "email_type": lead.email_type, "phone": lead.phone, "country": lead.country, "website": lead.website, "address": lead.address,
        "interactions": history,
        "notes": [{"id": str(note.id), "note": note.note, "author": note.author.full_name, "created_at": note.created_at.isoformat()} for note in notes],
    }


@router.patch("/leads/{lead_id}")
def update_lead(lead_id: uuid.UUID, payload: LeadUpdate, db: Session = Depends(get_db), user: User = Depends(require_roles("ADMIN", "MANAGER", "SALES"))):
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found.")
    interaction = db.scalar(select(Interaction).where(Interaction.lead_id == lead.id).order_by(Interaction.created_at.desc()))
    if interaction is None:
        raise HTTPException(status_code=404, detail="Lead interaction not found.")
    if user.role == "SALES" and interaction.assigned_to != user.id:
        raise HTTPException(status_code=403, detail="You can only update leads assigned to you.")
    changed = False
    if payload.status is not None:
        if payload.status not in STATUSES:
            raise HTTPException(status_code=422, detail="Choose a valid lead status.")
        old_status = interaction.status
        interaction.status = payload.status
        changed = True
        db.add(AuditLog(user_id=user.id, action="lead_status_changed", entity_type="lead", entity_id=str(lead.id), metadata_json={"from": old_status, "to": payload.status}))
    if "assigned_to" in payload.model_fields_set:
        if user.role not in {"ADMIN", "MANAGER"}:
            raise HTTPException(status_code=403, detail="Only managers can assign leads.")
        if payload.assigned_to is None:
            interaction.assigned_to = None
        else:
            assignee = db.get(User, payload.assigned_to)
            if assignee is None or not assignee.is_active:
                raise HTTPException(status_code=422, detail="Choose an active team member.")
            interaction.assigned_to = assignee.id
        changed = True
        db.add(AuditLog(user_id=user.id, action="lead_assigned", entity_type="lead", entity_id=str(lead.id), metadata_json={"assigned_to": str(interaction.assigned_to) if interaction.assigned_to else None}))
    if changed:
        from app.core.config import settings
        if settings.google_sheet_id:
            db.add(IntegrationJob(type="google_sheets_upsert", entity_id=interaction.id, status="pending"))
    db.commit()
    return _lead_row(lead, interaction, db)


@router.post("/leads/{lead_id}/notes", status_code=201)
def add_note(lead_id: uuid.UUID, payload: NoteInput, db: Session = Depends(get_db), user: User = Depends(require_roles("ADMIN", "MANAGER", "SALES"))):
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found.")
    if user.role == "SALES":
        latest_interaction = db.scalar(select(Interaction).where(Interaction.lead_id == lead.id).order_by(Interaction.created_at.desc()).limit(1))
        if latest_interaction is None or latest_interaction.assigned_to != user.id:
            raise HTTPException(status_code=403, detail="You can only add notes to leads assigned to you.")
    note_text = payload.note.strip()
    if not note_text:
        raise HTTPException(status_code=422, detail="Write a note before saving.")
    if payload.interaction_id:
        interaction = db.scalar(select(Interaction).where(Interaction.id == payload.interaction_id, Interaction.lead_id == lead.id))
        if interaction is None:
            raise HTTPException(status_code=422, detail="The selected interaction does not belong to this lead.")
    note = LeadNote(lead_id=lead.id, interaction_id=payload.interaction_id, author_user_id=user.id, note=note_text)
    db.add(note)
    db.add(AuditLog(user_id=user.id, action="lead_note_added", entity_type="lead", entity_id=str(lead.id), metadata_json={}))
    db.commit()
    return {"id": str(note.id), "note": note.note, "created_at": note.created_at.isoformat()}


@router.get("/leads/{lead_id}/business-card")
def get_business_card(lead_id: uuid.UUID, side: str = "front", interaction_id: uuid.UUID | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if side not in {"front", "back"}:
        raise HTTPException(status_code=422, detail="Choose front or back for the card side.")
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found.")
    if user.role == "SALES":
        assigned_interaction = db.scalar(select(Interaction.id).where(Interaction.lead_id == lead.id, Interaction.assigned_to == user.id))
        latest_interaction = db.scalar(select(Interaction).where(Interaction.lead_id == lead.id).order_by(Interaction.created_at.desc()).limit(1))
        if not assigned_interaction and (latest_interaction is None or latest_interaction.assigned_to is not None):
            raise HTTPException(status_code=404, detail="Lead not found.")
    query = select(BusinessCard).where(BusinessCard.lead_id == lead.id)
    if interaction_id:
        query = query.where(BusinessCard.interaction_id == interaction_id)
    else:
        query = query.order_by(BusinessCard.created_at.desc())
    card = db.scalar(query)
    if card is None:
        raise HTTPException(status_code=404, detail="No business card is stored for this lead.")
    path = card.storage_path if side == "front" else card.back_storage_path
    mime_type = card.mime_type if side == "front" else card.back_mime_type
    if not path or not mime_type:
        raise HTTPException(status_code=404, detail=f"No {side} image is stored for this lead.")
    try:
        content = storage.read(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="The private business-card image is unavailable.") from None
    return StreamingResponse(io.BytesIO(content), media_type=mime_type, headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


@router.delete("/leads/{lead_id}", status_code=204, dependencies=[Depends(require_roles("ADMIN"))])
def delete_lead(lead_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found.")
    cards = db.scalars(select(BusinessCard).where(BusinessCard.lead_id == lead.id)).all()
    db.add(AuditLog(user_id=user.id, action="lead_deleted", entity_type="lead", entity_id=str(lead.id), metadata_json={"lead_code": lead.lead_code}))
    for card in cards:
        storage.delete(card.storage_path)
        if card.back_storage_path:
            storage.delete(card.back_storage_path)
    db.delete(lead)
    db.commit()


@router.get("/team")
def list_team(db: Session = Depends(get_db), user: User = Depends(require_roles("ADMIN", "MANAGER"))):
    users = db.scalars(select(User).order_by(User.full_name)).all()
    return [{"id": str(item.id), "email": item.email, "full_name": item.full_name, "role": item.role, "is_active": item.is_active} for item in users]


@router.patch("/team/{user_id}")
def update_team_member(user_id: uuid.UUID, payload: UserUpdate, db: Session = Depends(get_db), actor: User = Depends(require_roles("ADMIN"))):
    member = db.get(User, user_id)
    if member is None:
        raise HTTPException(status_code=404, detail="Team member not found.")
    if member.id == actor.id and (not payload.is_active or payload.role != "ADMIN"):
        raise HTTPException(status_code=422, detail="You cannot deactivate or demote your own admin account.")
    member.full_name, member.role, member.is_active = payload.full_name.strip(), payload.role, payload.is_active
    db.add(AuditLog(user_id=actor.id, action="team_member_updated", entity_type="user", entity_id=str(member.id), metadata_json={"role": member.role, "active": member.is_active}))
    db.commit()
    return {"id": str(member.id), "email": member.email, "full_name": member.full_name, "role": member.role, "is_active": member.is_active}


@router.get("/events")
def list_events(db: Session = Depends(get_db), user: User = Depends(current_user)):
    events = db.scalars(select(Event).order_by(Event.start_date.desc().nullslast(), Event.name)).all()
    return [{"id": str(item.id), "name": item.name, "slug": item.slug, "start_date": item.start_date.isoformat() if item.start_date else None, "end_date": item.end_date.isoformat() if item.end_date else None, "location": item.location, "is_active": item.is_active} for item in events]


@router.post("/events", status_code=201)
def create_event(payload: EventInput, db: Session = Depends(get_db), user: User = Depends(require_roles("ADMIN"))):
    event = Event(**payload.model_dump())
    db.add(event)
    db.flush()
    db.add(AuditLog(user_id=user.id, action="event_created", entity_type="event", entity_id=str(event.id), metadata_json={"slug": event.slug}))
    db.commit()
    return {"id": str(event.id), "name": event.name, "slug": event.slug, "is_active": event.is_active}


@router.patch("/events/{event_id}")
def update_event(event_id: uuid.UUID, payload: EventInput, db: Session = Depends(get_db), user: User = Depends(require_roles("ADMIN"))):
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    for key, value in payload.model_dump().items():
        setattr(event, key, value)
    db.add(AuditLog(user_id=user.id, action="event_updated", entity_type="event", entity_id=str(event.id), metadata_json={"slug": event.slug, "active": event.is_active}))
    db.commit()
    return {"id": str(event.id), "name": event.name, "slug": event.slug, "is_active": event.is_active}


@router.get("/settings")
def get_settings(user: User = Depends(require_roles("ADMIN", "MANAGER"))):
    return {
        "app_name": "LatentSig Connect", "default_event_slug": settings.default_event_slug,
        "storage_provider": settings.storage_provider,
        "google_sheets_enabled": bool(settings.google_sheet_id and (settings.google_service_account_json or (settings.google_service_account_email and settings.google_private_key))),
        "whatsapp_configured": bool(settings.whatsapp_number),
        "business_card_retention_days": settings.business_card_retention_days,
    }
