import re
import uuid
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import current_user, require_roles
from app.db.models import (
    AuditLog, Event, EventProfile, EventRegistrant, EventSession, EventStaff,
    Interaction, Lead, Meeting, StaffCardCapture, User,
)
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["event workspaces"])
MANAGERS = ("ADMIN", "MANAGER")
STAFF = ("ADMIN", "MANAGER", "SALES")
MEETING_STATUSES = {"requested", "confirmed", "completed", "cancelled"}


class ProfileInput(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    location: str | None = Field(default=None, max_length=180)
    venue: str | None = Field(default=None, max_length=180)
    sessions_template: list[dict] = Field(default_factory=list, max_length=100)


class EventFromProfileInput(BaseModel):
    profile_id: uuid.UUID
    name: str = Field(min_length=2, max_length=180)
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    start_date: date | None = None
    end_date: date | None = None
    is_active: bool = True


class SessionInput(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    venue: str | None = Field(default=None, max_length=180)
    is_active: bool = True


class StaffInput(BaseModel):
    user_ids: list[uuid.UUID] = Field(max_length=300)


class MeetingInput(BaseModel):
    lead_id: uuid.UUID
    interaction_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    employee_id: uuid.UUID | None = None
    topics: list[str] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=10000)
    demo_presented: bool = False
    status: Literal["requested", "confirmed", "completed", "cancelled"] = "requested"
    next_steps: str = Field(default="", max_length=10000)
    follow_up_due_at: datetime | None = None


class MeetingPatch(BaseModel):
    scheduled_at: datetime | None = None
    employee_id: uuid.UUID | None = None
    topics: list[str] | None = Field(default=None, max_length=30)
    notes: str | None = Field(default=None, max_length=10000)
    demo_presented: bool | None = None
    status: Literal["requested", "confirmed", "completed", "cancelled"] | None = None
    next_steps: str | None = Field(default=None, max_length=10000)
    follow_up_due_at: datetime | None = None


class MeetingConfirmInput(BaseModel):
    event_id: uuid.UUID | None = None
    interaction_id: uuid.UUID | None = None
    topics: list[str] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=10000)
    demo_presented: bool = False
    next_steps: str = Field(default="", max_length=10000)
    follow_up_due_at: datetime | None = None


class RegistrantMatchInput(BaseModel):
    lead_id: uuid.UUID


def _event_or_404(db: Session, event_id: uuid.UUID) -> Event:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    return event


def _session_json(item: EventSession) -> dict:
    return {
        "id": str(item.id), "event_id": str(item.event_id), "name": item.name, "slug": item.slug,
        "starts_at": item.starts_at.isoformat() if item.starts_at else None,
        "ends_at": item.ends_at.isoformat() if item.ends_at else None,
        "venue": item.venue, "is_active": item.is_active,
    }


def _meeting_json(item: Meeting, db: Session) -> dict:
    employee = db.get(User, item.employee_id) if item.employee_id else None
    lead = db.get(Lead, item.lead_id)
    return {
        "id": str(item.id), "event_id": str(item.event_id) if item.event_id else None,
        "lead_id": str(item.lead_id), "interaction_id": str(item.interaction_id) if item.interaction_id else None,
        "full_name": lead.full_name if lead else None, "company": lead.company if lead else None,
        "scheduled_at": item.scheduled_at.isoformat() if item.scheduled_at else None,
        "employee_id": str(item.employee_id) if item.employee_id else None,
        "employee_name": employee.full_name if employee else None, "topics": item.topics,
        "notes": item.notes, "demo_presented": item.demo_presented, "status": item.status,
        "next_steps": item.next_steps,
        "follow_up_due_at": item.follow_up_due_at.isoformat() if item.follow_up_due_at else None,
        "created_at": item.created_at.isoformat(),
    }


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def find_attendee_candidates(db: Session, event_id: uuid.UUID | None, fields: dict, limit: int = 8) -> list[dict]:
    """Return identifier and name/company candidates without treating imported rows as live leads."""
    email = (fields.get("email") or "").strip().casefold()
    phone = re.sub(r"\D", "", fields.get("phone") or "")
    name, company = _norm(fields.get("full_name")), _norm(fields.get("company"))
    results: list[dict] = []
    leads = db.scalars(select(Lead).order_by(Lead.created_at.desc()).limit(5000)).all()
    for lead in leads:
        email_match = bool(email and lead.normalized_email and email == lead.normalized_email.casefold())
        phone_match = bool(phone and lead.normalized_phone and phone == re.sub(r"\D", "", lead.normalized_phone))
        name_score = SequenceMatcher(None, name, _norm(lead.full_name)).ratio() if name and lead.full_name else 0
        company_score = SequenceMatcher(None, company, _norm(lead.company)).ratio() if company and lead.company else 0
        exact_name_company = bool(name and company and name == _norm(lead.full_name) and company == _norm(lead.company))
        score = 1.0 if email_match or phone_match or exact_name_company else 0.68 * name_score + 0.32 * company_score
        if email_match or phone_match or exact_name_company or (name_score >= 0.90 and company_score >= 0.88):
            results.append({
                "kind": "lead", "id": str(lead.id), "full_name": lead.full_name, "company": lead.company,
                "email": lead.email, "phone": lead.phone, "score": round(score, 3),
                "confidence": "high" if email_match or phone_match or exact_name_company else "possible",
                "matched_by": "email" if email_match else "phone" if phone_match else "name_company",
            })

    registrants_query = select(EventRegistrant)
    if event_id:
        registrants_query = registrants_query.where(EventRegistrant.event_id == event_id)
    registrants = db.scalars(registrants_query.order_by(EventRegistrant.created_at.desc()).limit(5000)).all()
    for registrant in registrants:
        email_match = bool(email and registrant.email and email == registrant.email.strip().casefold())
        phone_match = bool(phone and registrant.phone and phone == re.sub(r"\D", "", registrant.phone))
        name_score = SequenceMatcher(None, name, _norm(registrant.full_name)).ratio() if name and registrant.full_name else 0
        company_score = SequenceMatcher(None, company, _norm(registrant.company)).ratio() if company and registrant.company else 0
        exact_name_company = bool(name and company and name == _norm(registrant.full_name) and company == _norm(registrant.company))
        score = 1.0 if email_match or phone_match or exact_name_company else 0.68 * name_score + 0.32 * company_score
        if email_match or phone_match or exact_name_company or (name_score >= 0.90 and company_score >= 0.88):
            results.append({
                "kind": "registrant", "id": str(registrant.id), "full_name": registrant.full_name,
                "company": registrant.company, "email": registrant.email, "phone": registrant.phone,
                "profile_id": registrant.profile_id, "match_status": registrant.match_status,
                "score": round(score, 3), "confidence": "high" if email_match or phone_match or exact_name_company else "possible",
                "matched_by": "email" if email_match else "phone" if phone_match else "name_company",
            })
    results.sort(key=lambda item: (item["score"], item["kind"] == "lead"), reverse=True)
    return results[:limit]


@router.get("/event-profiles")
def list_event_profiles(db: Session = Depends(get_db), user: User = Depends(current_user)):
    profiles = db.scalars(select(EventProfile).order_by(EventProfile.name)).all()
    return [{
        "id": str(item.id), "name": item.name, "location": item.location, "venue": item.venue,
        "sessions_template": item.sessions_template, "created_at": item.created_at.isoformat(),
    } for item in profiles]


@router.post("/event-profiles", status_code=201)
def create_event_profile(payload: ProfileInput, db: Session = Depends(get_db), user: User = Depends(require_roles(*MANAGERS))):
    profile = EventProfile(**payload.model_dump(), created_by=user.id)
    db.add(profile)
    db.flush()
    db.flush()
    db.add(AuditLog(user_id=user.id, action="event_profile_created", entity_type="event_profile", entity_id=str(profile.id), metadata_json={}))
    db.commit()
    return {"id": str(profile.id), "name": profile.name, "location": profile.location, "venue": profile.venue, "sessions_template": profile.sessions_template}


@router.post("/events/from-profile", status_code=201)
def create_event_from_profile(payload: EventFromProfileInput, db: Session = Depends(get_db), user: User = Depends(require_roles(*MANAGERS))):
    profile = db.get(EventProfile, payload.profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Event profile not found.")
    event = Event(
        name=payload.name, slug=payload.slug,
        start_date=payload.start_date,
        end_date=payload.end_date,
        location=profile.location, venue=profile.venue, profile_id=profile.id, is_active=payload.is_active,
    )
    db.add(event)
    db.flush()
    for template in profile.sessions_template:
        name = str(template.get("name") or "").strip()
        if not name:
            continue
        session_slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:120] or f"session-{uuid.uuid4().hex[:8]}"
        db.add(EventSession(event_id=event.id, name=name[:180], slug=session_slug, venue=template.get("venue") or profile.venue))
    db.add(AuditLog(user_id=user.id, action="event_created_from_profile", entity_type="event", entity_id=str(event.id), metadata_json={"profile_id": str(profile.id)}))
    db.commit()
    return {"id": str(event.id), "name": event.name, "slug": event.slug, "profile_id": str(profile.id)}


@router.get("/events/{event_id}/sessions")
def list_event_sessions(event_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _event_or_404(db, event_id)
    sessions = db.scalars(select(EventSession).where(EventSession.event_id == event_id).order_by(EventSession.starts_at, EventSession.name)).all()
    return [_session_json(item) for item in sessions]


@router.post("/events/{event_id}/sessions", status_code=201)
def create_event_session(event_id: uuid.UUID, payload: SessionInput, db: Session = Depends(get_db), user: User = Depends(require_roles(*MANAGERS))):
    _event_or_404(db, event_id)
    if payload.starts_at and payload.ends_at and payload.ends_at <= payload.starts_at:
        raise HTTPException(status_code=422, detail="Session end time must be after its start time.")
    item = EventSession(event_id=event_id, **payload.model_dump())
    db.add(item)
    db.flush()
    db.add(AuditLog(user_id=user.id, action="event_session_created", entity_type="event_session", entity_id=str(item.id), metadata_json={"slug": item.slug}))
    db.commit()
    return _session_json(item)


@router.patch("/events/{event_id}/sessions/{session_id}")
def update_event_session(event_id: uuid.UUID, session_id: uuid.UUID, payload: SessionInput, db: Session = Depends(get_db), user: User = Depends(require_roles(*MANAGERS))):
    item = db.scalar(select(EventSession).where(EventSession.id == session_id, EventSession.event_id == event_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Event session not found.")
    if payload.starts_at and payload.ends_at and payload.ends_at <= payload.starts_at:
        raise HTTPException(status_code=422, detail="Session end time must be after its start time.")
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    db.add(AuditLog(user_id=user.id, action="event_session_updated", entity_type="event_session", entity_id=str(item.id), metadata_json={}))
    db.commit()
    return _session_json(item)


@router.delete("/events/{event_id}/sessions/{session_id}", status_code=204)
def delete_event_session(event_id: uuid.UUID, session_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_roles(*MANAGERS))):
    item = db.scalar(select(EventSession).where(EventSession.id == session_id, EventSession.event_id == event_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Event session not found.")
    db.delete(item)
    db.commit()


@router.get("/events/{event_id}/staff")
def list_event_staff(event_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _event_or_404(db, event_id)
    rows = db.execute(select(EventStaff, User).join(User, User.id == EventStaff.user_id).where(EventStaff.event_id == event_id).order_by(User.full_name)).all()
    return [{"id": str(member.id), "user_id": str(person.id), "full_name": person.full_name, "email": person.email, "role": member.role} for member, person in rows]


@router.put("/events/{event_id}/staff")
def assign_event_staff(event_id: uuid.UUID, payload: StaffInput, db: Session = Depends(get_db), actor: User = Depends(require_roles(*MANAGERS))):
    _event_or_404(db, event_id)
    user_ids = list(dict.fromkeys(payload.user_ids))
    active = db.scalars(select(User).where(User.id.in_(user_ids), User.is_active.is_(True))).all() if user_ids else []
    if len(active) != len(user_ids):
        raise HTTPException(status_code=422, detail="Choose only active team members.")
    existing = db.scalars(select(EventStaff).where(EventStaff.event_id == event_id)).all()
    by_user = {row.user_id: row for row in existing}
    for item in existing:
        if item.user_id not in user_ids:
            db.delete(item)
    for user_id in user_ids:
        if user_id not in by_user:
            db.add(EventStaff(event_id=event_id, user_id=user_id))
    db.add(AuditLog(user_id=actor.id, action="event_staff_updated", entity_type="event", entity_id=str(event_id), metadata_json={"staff_count": len(user_ids)}))
    db.commit()
    return {"assigned": len(user_ids)}


@router.get("/events/{event_id}/dashboard")
def event_dashboard(event_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    event = _event_or_404(db, event_id)
    registrants = db.scalars(select(EventRegistrant).where(EventRegistrant.event_id == event.id)).all()
    total_registrants = len({("profile", item.profile_id) if item.profile_id else ("source", item.source_key) for item in registrants})
    shortlist_total = sum(bool(item.shortlist_status) for item in registrants)
    shortlist_strong = sum((item.shortlist_status or "").strip().casefold() == "strong" for item in registrants)
    cse_total = sum(bool(item.cse_status) for item in registrants)
    matched = sum(item.match_status == "matched" for item in registrants)
    submissions = db.scalar(select(func.count(Interaction.id)).where(
        Interaction.event_id == event.id,
        Interaction.capture_method.in_(["manual", "business_card"]),
        Interaction.synthetic_test.is_(False), Interaction.exclude_from_analytics.is_(False),
    )) or 0
    submitted_contacts = db.scalar(select(func.count(func.distinct(Interaction.lead_id))).where(
        Interaction.event_id == event.id,
        Interaction.capture_method.in_(["manual", "business_card"]),
        Interaction.synthetic_test.is_(False), Interaction.exclude_from_analytics.is_(False),
    )) or 0
    meetings = db.scalar(select(func.count(Meeting.id)).where(
        Meeting.event_id == event.id, Meeting.status.in_(["confirmed", "completed"]),
    )) or 0
    staff_confirmed = db.scalar(select(func.count(StaffCardCapture.id)).where(
        StaffCardCapture.event_id == event.id, StaffCardCapture.status == "linked",
        StaffCardCapture.synthetic_test.is_(False), StaffCardCapture.exclude_from_analytics.is_(False),
    )) or 0
    pending_matches = db.scalar(select(func.count(StaffCardCapture.id)).where(
        StaffCardCapture.event_id == event.id, StaffCardCapture.status == "pending_match",
        StaffCardCapture.synthetic_test.is_(False),
    )) or 0
    outstanding = db.scalar(select(func.count(Meeting.id)).where(
        Meeting.event_id == event.id, Meeting.follow_up_due_at.is_not(None), Meeting.status.not_in(["completed", "cancelled"]),
    )) or 0
    return {
        "event": {"id": str(event.id), "name": event.name, "slug": event.slug, "start_date": event.start_date.isoformat() if event.start_date else None,
                  "end_date": event.end_date.isoformat() if event.end_date else None, "location": event.location, "venue": event.venue},
        "research": {"unique_registrants": total_registrants,
                     "shortlist_progress": {"rows_with_status": shortlist_total, "strong": shortlist_strong, "total_rows": len(registrants)},
                     "cse_research_progress": {"rows_with_status": cse_total, "total_rows": len(registrants)},
                     "shortlist_rows": shortlist_total, "strong_shortlist": shortlist_strong,
                     "cse_research_rows": cse_total, "matched_registrants": matched, "unmatched_registrants": total_registrants - matched},
        "activity": {"submissions": submissions, "unique_submitted_contacts": submitted_contacts,
                     "staff_confirmed_encounters": staff_confirmed, "confirmed_meetings": meetings,
                     "outstanding_follow_ups": outstanding, "unmatched_visitors": (total_registrants - matched) + pending_matches,
                     "pending_card_matches": pending_matches},
    }


@router.get("/events/{event_id}/meetings")
def list_event_meetings(event_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _event_or_404(db, event_id)
    meetings = db.scalars(select(Meeting).where(Meeting.event_id == event_id).order_by(Meeting.scheduled_at.desc().nullslast(), Meeting.created_at.desc())).all()
    return [_meeting_json(item, db) for item in meetings]


@router.get("/leads/{lead_id}/meetings")
def list_lead_meetings(lead_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found.")
    if user.role == "SALES":
        access = db.scalar(select(Interaction.id).where(Interaction.lead_id == lead_id, Interaction.assigned_to == user.id))
        if not access:
            raise HTTPException(status_code=404, detail="Lead not found.")
    meetings = db.scalars(select(Meeting).where(Meeting.lead_id == lead_id).order_by(Meeting.created_at.desc())).all()
    return [_meeting_json(item, db) for item in meetings]


@router.post("/events/{event_id}/meetings", status_code=201)
def create_event_meeting(event_id: uuid.UUID, payload: MeetingInput, db: Session = Depends(get_db), user: User = Depends(require_roles(*STAFF))):
    _event_or_404(db, event_id)
    if user.role == "SALES" and not db.scalar(select(EventStaff.id).where(EventStaff.event_id == event_id, EventStaff.user_id == user.id)):
        raise HTTPException(status_code=403, detail="You are not assigned to work on this event.")
    lead = db.get(Lead, payload.lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found.")
    interaction = None
    if payload.interaction_id:
        interaction = db.get(Interaction, payload.interaction_id)
        if interaction is None or interaction.lead_id != lead.id or interaction.event_id != event_id:
            raise HTTPException(status_code=422, detail="The selected encounter does not belong to this event and contact.")
    employee_id = payload.employee_id or user.id
    if user.role == "SALES" and employee_id != user.id:
        raise HTTPException(status_code=403, detail="You can assign the meeting only to yourself.")
    employee = db.get(User, employee_id) if employee_id else None
    if employee_id and (employee is None or not employee.is_active):
        raise HTTPException(status_code=422, detail="Choose a team member for this meeting.")
    item = Meeting(event_id=event_id, created_by=user.id, employee_id=employee_id, **payload.model_dump(exclude={"employee_id"}))
    db.add(item)
    db.flush()
    db.add(AuditLog(user_id=user.id, action="meeting_recorded", entity_type="meeting", entity_id=str(item.id), metadata_json={"status": item.status}))
    db.commit()
    return _meeting_json(item, db)


@router.post("/leads/{lead_id}/meetings/confirm", status_code=201)
def confirm_meeting(lead_id: uuid.UUID, payload: MeetingConfirmInput, db: Session = Depends(get_db), user: User = Depends(require_roles(*STAFF))):
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found.")
    interaction = db.get(Interaction, payload.interaction_id) if payload.interaction_id else db.scalar(
        select(Interaction).where(Interaction.lead_id == lead.id).order_by(Interaction.created_at.desc()).limit(1)
    )
    if interaction is None or interaction.lead_id != lead.id:
        raise HTTPException(status_code=422, detail="Choose an encounter for this meeting.")
    event_id = payload.event_id or interaction.event_id
    if event_id and interaction.event_id != event_id:
        raise HTTPException(status_code=422, detail="The selected encounter belongs to a different event.")
    if user.role == "SALES" and event_id and not db.scalar(select(EventStaff.id).where(EventStaff.event_id == event_id, EventStaff.user_id == user.id)):
        raise HTTPException(status_code=403, detail="You are not assigned to work on this event.")
    if user.role == "SALES" and interaction.assigned_to not in (None, user.id):
        raise HTTPException(status_code=403, detail="You can only confirm meetings for work assigned to you.")
    item = Meeting(
        event_id=event_id, lead_id=lead.id, interaction_id=interaction.id,
        scheduled_at=datetime.now(timezone.utc), employee_id=user.id, topics=payload.topics,
        notes=payload.notes, demo_presented=payload.demo_presented, status="confirmed",
        next_steps=payload.next_steps, follow_up_due_at=payload.follow_up_due_at, created_by=user.id,
    )
    interaction.status = "meeting"
    db.add(item)
    db.flush()
    db.add(AuditLog(user_id=user.id, action="meeting_confirmed", entity_type="meeting", entity_id=str(item.id), metadata_json={"lead_id": str(lead.id), "event_id": str(event_id) if event_id else None}))
    db.commit()
    return _meeting_json(item, db)


@router.patch("/meetings/{meeting_id}")
def update_meeting(meeting_id: uuid.UUID, payload: MeetingPatch, db: Session = Depends(get_db), user: User = Depends(require_roles(*STAFF))):
    item = db.get(Meeting, meeting_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Meeting not found.")
    if user.role == "SALES" and item.employee_id not in (None, user.id):
        raise HTTPException(status_code=403, detail="You can update meetings assigned to you.")
    if payload.employee_id is not None and not db.get(User, payload.employee_id):
        raise HTTPException(status_code=422, detail="Choose an active team member.")
    if user.role == "SALES" and payload.employee_id not in (None, user.id):
        raise HTTPException(status_code=403, detail="You can assign the meeting only to yourself.")
    for key in payload.model_fields_set:
        setattr(item, key, getattr(payload, key))
    db.add(AuditLog(user_id=user.id, action="meeting_updated", entity_type="meeting", entity_id=str(item.id), metadata_json={"status": item.status}))
    db.commit()
    return _meeting_json(item, db)


@router.get("/events/{event_id}/research/registrants/{registrant_id}/matches")
def registrant_matches(event_id: uuid.UUID, registrant_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _event_or_404(db, event_id)
    registrant = db.scalar(select(EventRegistrant).where(EventRegistrant.id == registrant_id, EventRegistrant.event_id == event_id))
    if registrant is None:
        raise HTTPException(status_code=404, detail="Research registrant not found.")
    return find_attendee_candidates(db, event_id, {
        "full_name": registrant.full_name, "company": registrant.company,
        "email": registrant.email, "phone": registrant.phone,
    })


@router.post("/events/{event_id}/research/registrants/{registrant_id}/match")
def match_registrant(event_id: uuid.UUID, registrant_id: uuid.UUID, payload: RegistrantMatchInput, db: Session = Depends(get_db), user: User = Depends(require_roles(*MANAGERS))):
    registrant = db.scalar(select(EventRegistrant).where(EventRegistrant.id == registrant_id, EventRegistrant.event_id == event_id))
    lead = db.get(Lead, payload.lead_id)
    if registrant is None or lead is None:
        raise HTTPException(status_code=404, detail="Research registrant or lead not found.")
    registrant.matched_lead_id = lead.id
    registrant.match_status = "matched"
    db.add(AuditLog(user_id=user.id, action="research_registrant_matched", entity_type="event_registrant", entity_id=str(registrant.id), metadata_json={"lead_id": str(lead.id)}))
    db.commit()
    return {"id": str(registrant.id), "matched_lead_id": str(lead.id), "match_status": registrant.match_status}
