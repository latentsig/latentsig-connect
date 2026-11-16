import re
import uuid
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.security import current_user, require_roles
from app.db.models import (
    AuditLog, Event, EventEncounter, EventProfile, EventRegistrant, EventSession, EventStaff,
    Interaction, Lead, Meeting, ResearchImportBatch, StaffCardCapture, User,
)
from app.db.session import get_db
from app.services.research_matching import (
    find_attendee_candidates, group_registrants, mark_registrant_identity_matched,
    registrant_identity_key, registrant_identity_token,
)

router = APIRouter(prefix="/admin", tags=["event workspaces"])
MANAGERS = ("ADMIN", "MANAGER")
STAFF = ("ADMIN", "MANAGER", "SALES")
MEETING_STATUSES = {"requested", "confirmed", "completed", "cancelled"}


class SessionTemplateInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=180)
    venue: str | None = Field(default=None, max_length=180)
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @model_validator(mode="after")
    def validate_session_range(self):
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("Session end time must be after its start time.")
        return self


class ProfileInput(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    location: str | None = Field(default=None, max_length=180)
    venue: str | None = Field(default=None, max_length=180)
    sessions_template: list[SessionTemplateInput] = Field(default_factory=list, max_length=100)


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


class ResearchEncounterInput(BaseModel):
    registrant_id: uuid.UUID
    session_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None
    encounter_type: Literal["met", "demo", "meeting"]
    scheduled_at: datetime | None = None
    topics: list[str] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=10000)
    demo_presented: bool = False
    status: Literal["requested", "confirmed", "completed", "cancelled"] | None = None
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


class LeadMeetingInput(BaseModel):
    interaction_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    employee_id: uuid.UUID | None = None
    topics: list[str] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=10000)
    demo_presented: bool = False
    status: Literal["requested", "confirmed", "completed", "cancelled"] = "requested"
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
        "id": str(item.id), "kind": "lead_meeting", "event_id": str(item.event_id) if item.event_id else None,
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


def _source_header_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _source_value(raw_data: dict, *header_names: str) -> str | None:
    normalized = {_source_header_key(str(key)): value for key, value in (raw_data or {}).items()}
    for name in header_names:
        value = normalized.get(_source_header_key(name))
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _priority_group_json(group: list[EventRegistrant], identity: tuple[str, str], priority: str, met: bool) -> dict:
    def quality(row: EventRegistrant) -> tuple[int, int]:
        values = row.raw_data or {}
        has_pitch = any(_source_value(values, field) for field in ("Opener", "Suggested Angle", "LatentSig can pitch", "What Latent Sig can pitch"))
        has_fit = _source_value(values, "Latent Sig Fit", "Fit") is not None
        return (int(has_pitch) + int(has_fit), int(row.sheet_name.casefold() == "strong shortlist"))

    row = max(group, key=quality)
    raw = row.raw_data or {}
    return {
        "registrant_id": str(row.id), "identity_key": f"{identity[0]}:{identity[1]}",
        "profile_id": row.profile_id, "full_name": row.full_name, "company": row.company,
        "job_title": row.job_title, "sheet_name": row.sheet_name, "source_row": row.source_row,
        "priority": priority, "relationship": _source_value(raw, "Relationship"),
        "fit": _source_value(raw, "Latent Sig Fit", "Fit"),
        "pitch": _source_value(raw, "Opener", "Suggested Angle", "LatentSig can pitch", "What Latent Sig can pitch"),
        "met": met,
    }


def _encounter_json(item: EventEncounter, db: Session) -> dict:
    registrant = db.get(EventRegistrant, item.registrant_id) if item.registrant_id else None
    lead = db.get(Lead, item.lead_id) if item.lead_id else None
    employee = db.get(User, item.employee_id) if item.employee_id else None
    session = db.get(EventSession, item.session_id) if item.session_id else None
    return {
        "id": str(item.id), "event_id": str(item.event_id),
        "registrant_id": str(item.registrant_id) if item.registrant_id else None,
        "lead_id": str(item.lead_id) if item.lead_id else None,
        "profile_id": registrant.profile_id if registrant else None,
        "full_name": registrant.full_name if registrant else (lead.full_name if lead else None),
        "company": registrant.company if registrant else (lead.company if lead else None),
        "session_id": str(item.session_id) if item.session_id else None,
        "session_name": session.name if session else None,
        "employee_id": str(item.employee_id) if item.employee_id else None,
        "employee_name": employee.full_name if employee else None,
        "encounter_type": item.encounter_type,
        "encountered_at": item.encountered_at.isoformat(),
        "scheduled_at": item.scheduled_at.isoformat() if item.scheduled_at else None,
        "topics": item.topics or [], "notes": item.notes,
        "demo_presented": item.demo_presented, "status": item.status,
        "next_steps": item.next_steps,
        "follow_up_due_at": item.follow_up_due_at.isoformat() if item.follow_up_due_at else None,
        "synthetic_test": item.synthetic_test, "created_at": item.created_at.isoformat(),
    }


@router.get("/event-profiles")
def list_event_profiles(db: Session = Depends(get_db), user: User = Depends(current_user)):
    profiles = db.scalars(select(EventProfile).order_by(EventProfile.name)).all()
    return [{
        "id": str(item.id), "name": item.name, "location": item.location, "venue": item.venue,
        "sessions_template": item.sessions_template, "created_at": item.created_at.isoformat(),
    } for item in profiles]


@router.post("/event-profiles", status_code=201)
def create_event_profile(payload: ProfileInput, db: Session = Depends(get_db), user: User = Depends(require_roles(*MANAGERS))):
    profile = EventProfile(**payload.model_dump(mode="json"), created_by=user.id)
    db.add(profile)
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
        session_template = SessionTemplateInput.model_validate(template)
        name = session_template.name
        session_slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:120] or f"session-{uuid.uuid4().hex[:8]}"
        db.add(EventSession(
            event_id=event.id, name=name, slug=session_slug,
            venue=session_template.venue or profile.venue,
            starts_at=session_template.starts_at, ends_at=session_template.ends_at,
        ))
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
    registrant_groups = group_registrants(registrants)
    total_registrants = len(registrant_groups)
    shortlist_total = sum(bool(item.shortlist_status) for item in registrants)
    shortlist_strong = sum((item.shortlist_status or "").strip().casefold() == "strong" for item in registrants)
    cse_total = sum(bool(item.cse_status) for item in registrants)
    matched = sum(
        len({item.matched_lead_id for item in group if item.matched_lead_id}) == 1
        and not any(item.match_status == "suggested" for item in group)
        for group in registrant_groups.values()
    )
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
    staff_manual_captures = db.scalar(select(func.count(Interaction.id)).where(
        Interaction.event_id == event.id, Interaction.source == "staff_quick_capture",
        Interaction.synthetic_test.is_(False), Interaction.exclude_from_analytics.is_(False),
    )) or 0
    meetings = (db.scalar(select(func.count(Meeting.id)).where(
        Meeting.event_id == event.id, Meeting.status.in_(["confirmed", "completed"]),
    )) or 0) + (db.scalar(select(func.count(EventEncounter.id)).where(
        EventEncounter.event_id == event.id, EventEncounter.encounter_type == "meeting",
        EventEncounter.status.in_(["confirmed", "completed"]),
        EventEncounter.synthetic_test.is_(False), EventEncounter.exclude_from_analytics.is_(False),
    )) or 0)
    staff_confirmed_filter = or_(
        EventEncounter.encounter_type.in_(["met", "demo"]),
        (EventEncounter.encounter_type == "meeting") & (EventEncounter.status == "completed"),
    )
    staff_confirmed = (db.scalar(select(func.count(EventEncounter.id)).where(
        EventEncounter.event_id == event.id, staff_confirmed_filter,
        EventEncounter.synthetic_test.is_(False), EventEncounter.exclude_from_analytics.is_(False),
    )) or 0) + (db.scalar(select(func.count(StaffCardCapture.id)).where(
        StaffCardCapture.event_id == event.id, StaffCardCapture.status == "linked",
        StaffCardCapture.synthetic_test.is_(False), StaffCardCapture.exclude_from_analytics.is_(False),
    )) or 0)
    unique_people_met = db.scalar(select(func.count(func.distinct(EventEncounter.identity_key))).where(
        EventEncounter.event_id == event.id, staff_confirmed_filter,
        EventEncounter.synthetic_test.is_(False), EventEncounter.exclude_from_analytics.is_(False),
    )) or 0
    staff_card_captures = db.scalar(select(func.count(StaffCardCapture.id)).where(
        StaffCardCapture.event_id == event.id,
        StaffCardCapture.synthetic_test.is_(False), StaffCardCapture.exclude_from_analytics.is_(False),
    )) or 0
    pending_matches = db.scalar(select(func.count(StaffCardCapture.id)).where(
        StaffCardCapture.event_id == event.id, StaffCardCapture.status == "pending_match",
        StaffCardCapture.synthetic_test.is_(False), StaffCardCapture.exclude_from_analytics.is_(False),
    )) or 0
    captured_leads = (
        select(Interaction.lead_id.label("lead_id"))
        .where(
            Interaction.event_id == event.id,
            Interaction.capture_method.in_(["manual", "business_card"]),
            Interaction.synthetic_test.is_(False),
            Interaction.exclude_from_analytics.is_(False),
        )
        .distinct()
        .subquery()
    )
    matched_leads = (
        select(EventRegistrant.matched_lead_id)
        .where(
            EventRegistrant.event_id == event.id,
            EventRegistrant.matched_lead_id.is_not(None),
        )
        .distinct()
    )
    unmatched_submissions = db.scalar(
        select(func.count())
        .select_from(captured_leads)
        .where(~captured_leads.c.lead_id.in_(matched_leads))
    ) or 0
    pending_capture_reviews = db.scalar(select(func.count(StaffCardCapture.id)).where(
        StaffCardCapture.event_id == event.id,
        StaffCardCapture.status.in_(["pending_review", "pending_match", "ocr_failed"]),
        StaffCardCapture.lead_id.is_(None),
        StaffCardCapture.synthetic_test.is_(False),
        StaffCardCapture.exclude_from_analytics.is_(False),
    )) or 0
    outstanding = (db.scalar(select(func.count(Meeting.id)).where(
        Meeting.event_id == event.id, Meeting.follow_up_due_at.is_not(None), Meeting.status.not_in(["completed", "cancelled"]),
    )) or 0) + (db.scalar(select(func.count(EventEncounter.id)).where(
        EventEncounter.event_id == event.id,
        EventEncounter.encounter_type == "meeting",
        EventEncounter.follow_up_due_at.is_not(None),
        EventEncounter.status.not_in(["completed", "cancelled"]),
        EventEncounter.synthetic_test.is_(False), EventEncounter.exclude_from_analytics.is_(False),
    )) or 0)
    return {
        "event": {"id": str(event.id), "name": event.name, "slug": event.slug, "start_date": event.start_date.isoformat() if event.start_date else None,
                  "end_date": event.end_date.isoformat() if event.end_date else None, "location": event.location, "venue": event.venue},
        "research": {"unique_registrants": total_registrants,
                     "shortlist_progress": {"rows_with_status": shortlist_total, "strong": shortlist_strong, "total_rows": len(registrants)},
                     "cse_research_progress": {"rows_with_status": cse_total, "total_rows": len(registrants)},
                     "shortlist_rows": shortlist_total, "strong_shortlist": shortlist_strong,
                     "cse_research_rows": cse_total, "matched_registrants": matched, "unmatched_registrants": total_registrants - matched},
        "activity": {"submissions": submissions, "unique_submitted_contacts": submitted_contacts,
                     "staff_manual_captures": staff_manual_captures,
                     "staff_confirmed_encounters": staff_confirmed, "unique_people_met": unique_people_met,
                     "staff_card_captures": staff_card_captures, "confirmed_meetings": meetings,
                     "outstanding_follow_ups": outstanding,
                     "unmatched_visitors": unmatched_submissions + pending_capture_reviews,
                     "unmatched_submissions": unmatched_submissions,
                     "pending_card_matches": pending_matches},
    }


@router.get("/events/{event_id}/priority-panels")
def event_priority_panels(event_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    event = _event_or_404(db, event_id)
    latest_batch = db.scalar(
        select(ResearchImportBatch)
        .where(ResearchImportBatch.event_id == event.id, ResearchImportBatch.status == "imported")
        .order_by(ResearchImportBatch.imported_at.desc(), ResearchImportBatch.created_at.desc())
        .limit(1)
    )
    registrants_query = select(EventRegistrant).where(EventRegistrant.event_id == event.id)
    if latest_batch:
        registrants_query = registrants_query.where(EventRegistrant.last_import_batch_id == latest_batch.id)
    registrants = db.scalars(registrants_query.order_by(EventRegistrant.source_row)).all()
    groups = group_registrants(registrants)

    completed_encounters = db.scalars(select(EventEncounter.identity_key).where(
        EventEncounter.event_id == event.id,
        EventEncounter.synthetic_test.is_(False), EventEncounter.exclude_from_analytics.is_(False),
        or_(
            EventEncounter.encounter_type.in_(["met", "demo"]),
            (EventEncounter.encounter_type == "meeting") & (EventEncounter.status == "completed"),
        ),
    )).all()
    met_identity_keys = set(completed_encounters)
    completed_leads = set(db.scalars(select(Meeting.lead_id).where(
        Meeting.event_id == event.id, Meeting.status == "completed", Meeting.lead_id.is_not(None),
    )).all())

    must_meet: list[dict] = []
    opportunities: list[dict] = []
    must_meet_identity_keys: set[str] = set()
    for identity, group in groups.items():
        identity_key = f"{identity[0]}:{identity[1]}"
        met = identity_key in met_identity_keys or any(row.matched_lead_id in completed_leads for row in group if row.matched_lead_id)
        priority_values = {
            value.upper()
            for row in group
            if (value := _source_value(row.raw_data or {}, "Must-Meet", "Must Meet", "Priority"))
        }
        priority = "A" if "A" in priority_values else "B" if "B" in priority_values else None
        if priority and not met:
            must_meet.append(_priority_group_json(group, identity, priority, met))
            must_meet_identity_keys.add(identity_key)

        opportunity_rows = [row for row in group if
            (_source_value(row.raw_data or {}, "Relationship") or "").casefold() in {"client", "design partner"}
            and (_source_value(row.raw_data or {}, "Latent Sig Fit", "Fit") or "").casefold() == "strong"
        ]
        if not met and identity_key not in must_meet_identity_keys and opportunity_rows:
            opportunities.append(_priority_group_json(opportunity_rows, identity, "", met))

    priority_order = {"A": 0, "B": 1}
    must_meet.sort(key=lambda row: (
        priority_order[row["priority"]],
        0 if (row.get("fit") or "").casefold() == "strong" else 1,
        (row.get("company") or "").casefold(), (row.get("full_name") or "").casefold(),
    ))
    priority_counts = {
        priority: sum(1 for row in must_meet if row["priority"] == priority)
        for priority in ("A", "B")
    }
    opportunities.sort(key=lambda row: (
        0 if (row.get("relationship") or "").casefold() == "client" else 1,
        (row.get("company") or "").casefold(), (row.get("full_name") or "").casefold(),
    ))

    meetings = db.scalars(select(Meeting).where(
        Meeting.event_id == event.id, Meeting.follow_up_due_at.is_not(None),
        Meeting.status.not_in(["completed", "cancelled"]),
    ).order_by(Meeting.follow_up_due_at, Meeting.created_at).limit(100)).all()
    follow_ups: list[dict] = []
    for meeting in meetings:
        lead = db.get(Lead, meeting.lead_id)
        employee = db.get(User, meeting.employee_id) if meeting.employee_id else None
        follow_ups.append({
            "id": str(meeting.id), "kind": "meeting", "lead_id": str(meeting.lead_id),
            "full_name": lead.full_name if lead else None, "company": lead.company if lead else None,
            "due_at": meeting.follow_up_due_at.isoformat(), "next_steps": meeting.next_steps,
            "status": meeting.status, "owner": employee.full_name if employee else None,
        })
    encounters = db.scalars(select(EventEncounter).where(
        EventEncounter.event_id == event.id, EventEncounter.encounter_type == "meeting",
        EventEncounter.follow_up_due_at.is_not(None), EventEncounter.status.not_in(["completed", "cancelled"]),
        EventEncounter.synthetic_test.is_(False), EventEncounter.exclude_from_analytics.is_(False),
    ).order_by(EventEncounter.follow_up_due_at, EventEncounter.created_at).limit(100)).all()
    for encounter in encounters:
        registrant = db.get(EventRegistrant, encounter.registrant_id) if encounter.registrant_id else None
        lead = db.get(Lead, encounter.lead_id) if encounter.lead_id else None
        employee = db.get(User, encounter.employee_id) if encounter.employee_id else None
        follow_ups.append({
            "id": str(encounter.id), "kind": "research_meeting",
            "registrant_id": str(encounter.registrant_id) if encounter.registrant_id else None,
            "lead_id": str(encounter.lead_id) if encounter.lead_id else None,
            "full_name": registrant.full_name if registrant else (lead.full_name if lead else None),
            "company": registrant.company if registrant else (lead.company if lead else None),
            "due_at": encounter.follow_up_due_at.isoformat(), "next_steps": encounter.next_steps,
            "status": encounter.status, "owner": employee.full_name if employee else None,
        })
    follow_ups.sort(key=lambda row: row["due_at"])

    reconciliations = [row for row in registrants if row.reconciliation_required]
    reconciliations.sort(key=lambda row: (row.sheet_name.casefold(), row.source_row))
    pending_captures = db.scalars(select(StaffCardCapture).where(
        StaffCardCapture.event_id == event.id,
        StaffCardCapture.status.in_(["pending_review", "pending_match", "ocr_failed", "template_detected"]),
        StaffCardCapture.synthetic_test.is_(False), StaffCardCapture.exclude_from_analytics.is_(False),
    ).order_by(StaffCardCapture.created_at.desc()).limit(100)).all()
    return {
        "must_meet_next": {"total": len(must_meet), "priority_counts": priority_counts, "items": must_meet[:10]},
        "research_opportunities": {"total": len(opportunities), "items": opportunities[:10]},
        "follow_ups": {"total": len(follow_ups), "items": follow_ups[:50]},
        "needs_review": {
            "reconciliation_rows": len(reconciliations), "pending_card_captures": len(pending_captures),
            "reconciliation_items": [{
                "id": str(row.id), "full_name": row.full_name, "company": row.company,
                "sheet_name": row.sheet_name, "source_row": row.source_row,
                "errors": row.reconciliation_errors or [],
            } for row in reconciliations[:8]],
            "card_capture_items": [{
                "id": str(row.id), "status": row.status, "event_id": str(row.event_id),
                "captured_at": row.created_at.isoformat(), "filename": row.original_filename,
                "name": ((row.ocr_json or {}).get("full_name") or {}).get("value")
                if isinstance((row.ocr_json or {}).get("full_name"), dict)
                else (row.ocr_json or {}).get("full_name"),
            } for row in pending_captures[:8]],
        },
    }


@router.get("/events/{event_id}/meetings")
def list_event_meetings(event_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _event_or_404(db, event_id)
    if user.role == "SALES" and not db.scalar(select(EventStaff.id).where(
        EventStaff.event_id == event_id, EventStaff.user_id == user.id,
    )):
        raise HTTPException(status_code=403, detail="You are not assigned to work on this event.")
    meetings = db.scalars(select(Meeting).where(Meeting.event_id == event_id).order_by(Meeting.scheduled_at.desc().nullslast(), Meeting.created_at.desc())).all()
    results = [_meeting_json(item, db) for item in meetings]
    encounters = db.scalars(select(EventEncounter).where(
        EventEncounter.event_id == event_id,
        EventEncounter.encounter_type == "meeting",
        EventEncounter.synthetic_test.is_(False),
        EventEncounter.exclude_from_analytics.is_(False),
    ).order_by(EventEncounter.scheduled_at.desc().nullslast(), EventEncounter.created_at.desc())).all()
    for item in encounters:
        results.append({"kind": "research_meeting", **_encounter_json(item, db)})
    results.sort(key=lambda item: item.get("scheduled_at") or item.get("created_at") or "", reverse=True)
    return results


@router.get("/events/{event_id}/research/attendees/{registrant_id}/encounters")
def list_research_attendee_encounters(
    event_id: uuid.UUID,
    registrant_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    _event_or_404(db, event_id)
    registrant = db.get(EventRegistrant, registrant_id)
    if registrant is None or registrant.event_id != event_id:
        raise HTTPException(status_code=404, detail="Research attendee not found.")
    if user.role == "SALES" and not db.scalar(select(EventStaff.id).where(
        EventStaff.event_id == event_id, EventStaff.user_id == user.id,
    )):
        raise HTTPException(status_code=403, detail="You are not assigned to work on this event.")
    identity_key = registrant_identity_token(registrant)
    encounters = db.scalars(
        select(EventEncounter)
        .where(EventEncounter.event_id == event_id, EventEncounter.identity_key == identity_key)
        .order_by(EventEncounter.encountered_at.desc(), EventEncounter.created_at.desc())
    ).all()
    return [_encounter_json(item, db) for item in encounters]


@router.post("/events/{event_id}/encounters", status_code=201)
def create_research_attendee_encounter(
    event_id: uuid.UUID,
    payload: ResearchEncounterInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*STAFF)),
):
    _event_or_404(db, event_id)
    registrant = db.get(EventRegistrant, payload.registrant_id)
    if registrant is None or registrant.event_id != event_id:
        raise HTTPException(status_code=404, detail="Research attendee not found.")
    if user.role == "SALES" and not db.scalar(select(EventStaff.id).where(
        EventStaff.event_id == event_id, EventStaff.user_id == user.id,
    )):
        raise HTTPException(status_code=403, detail="You are not assigned to work on this event.")
    if payload.session_id:
        session = db.get(EventSession, payload.session_id)
        if session is None or session.event_id != event_id:
            raise HTTPException(status_code=422, detail="The selected session does not belong to this event.")
    employee_id = payload.employee_id or user.id
    if user.role == "SALES" and employee_id != user.id:
        raise HTTPException(status_code=403, detail="You can assign the encounter only to yourself.")
    employee = db.get(User, employee_id) if employee_id else None
    if employee_id and (employee is None or not employee.is_active):
        raise HTTPException(status_code=422, detail="Choose an active team member for this encounter.")
    status = payload.status or ("confirmed" if payload.encounter_type == "meeting" else "completed")
    if payload.encounter_type != "meeting" and status != "completed":
        raise HTTPException(status_code=422, detail="Met and demo records must be completed encounters.")
    item = EventEncounter(
        event_id=event_id,
        registrant_id=registrant.id,
        identity_key=registrant_identity_token(registrant),
        lead_id=registrant.matched_lead_id,
        session_id=payload.session_id,
        employee_id=employee_id,
        encounter_type=payload.encounter_type,
        scheduled_at=payload.scheduled_at,
        topics=payload.topics,
        notes=payload.notes,
        demo_presented=payload.demo_presented or payload.encounter_type == "demo",
        status=status,
        next_steps=payload.next_steps,
        follow_up_due_at=payload.follow_up_due_at,
        created_by=user.id,
    )
    db.add(item)
    db.flush()
    db.add(AuditLog(
        user_id=user.id,
        action="event_encounter_recorded",
        entity_type="event_encounter",
        entity_id=str(item.id),
        metadata_json={
            "event_id": str(event_id),
            "registrant_id": str(registrant.id),
            "encounter_type": item.encounter_type,
            "status": item.status,
        },
    ))
    db.commit()
    return _encounter_json(item, db)


@router.patch("/event-encounters/{encounter_id}")
def update_research_attendee_encounter(
    encounter_id: uuid.UUID,
    payload: MeetingPatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*STAFF)),
):
    item = db.get(EventEncounter, encounter_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Event encounter not found.")
    if user.role == "SALES":
        assigned = db.scalar(select(EventStaff.id).where(
            EventStaff.event_id == item.event_id, EventStaff.user_id == user.id,
        ))
        if not assigned or item.employee_id not in (None, user.id):
            raise HTTPException(status_code=403, detail="You can update encounters assigned to you.")
    if payload.employee_id is not None:
        employee = db.get(User, payload.employee_id)
        if employee is None or not employee.is_active:
            raise HTTPException(status_code=422, detail="Choose an active team member.")
    if user.role == "SALES" and payload.employee_id not in (None, user.id):
        raise HTTPException(status_code=403, detail="You can assign the encounter only to yourself.")
    if item.encounter_type != "meeting" and payload.status not in (None, "completed"):
        raise HTTPException(status_code=422, detail="Met and demo records must stay completed.")
    for key in payload.model_fields_set:
        value = getattr(payload, key)
        if key == "status" and value is None:
            continue
        setattr(item, key, value)
    db.add(AuditLog(
        user_id=user.id,
        action="event_encounter_updated",
        entity_type="event_encounter",
        entity_id=str(item.id),
        metadata_json={"event_id": str(item.event_id), "status": item.status},
    ))
    db.commit()
    return _encounter_json(item, db)


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
    if interaction and item.status in {"confirmed", "completed"}:
        interaction.status = "meeting"
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


@router.post("/leads/{lead_id}/meetings", status_code=201)
def create_lead_meeting(lead_id: uuid.UUID, payload: LeadMeetingInput, db: Session = Depends(get_db), user: User = Depends(require_roles(*STAFF))):
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found.")
    interaction = db.get(Interaction, payload.interaction_id) if payload.interaction_id else db.scalar(
        select(Interaction).where(Interaction.lead_id == lead.id).order_by(Interaction.created_at.desc()).limit(1)
    )
    if interaction is None or interaction.lead_id != lead.id:
        raise HTTPException(status_code=422, detail="Choose an encounter for this meeting.")
    if user.role == "SALES" and interaction.event_id and not db.scalar(select(EventStaff.id).where(EventStaff.event_id == interaction.event_id, EventStaff.user_id == user.id)):
        raise HTTPException(status_code=403, detail="You are not assigned to work on this event.")
    if user.role == "SALES" and interaction.assigned_to not in (None, user.id):
        raise HTTPException(status_code=403, detail="You can only record meetings for work assigned to you.")
    employee_id = payload.employee_id or user.id
    employee = db.get(User, employee_id) if employee_id else None
    if employee_id and (employee is None or not employee.is_active):
        raise HTTPException(status_code=422, detail="Choose an active team member for this meeting.")
    if user.role == "SALES" and employee_id != user.id:
        raise HTTPException(status_code=403, detail="You can assign the meeting only to yourself.")
    item = Meeting(
        event_id=interaction.event_id, lead_id=lead.id, interaction_id=interaction.id,
        scheduled_at=payload.scheduled_at, employee_id=employee_id, topics=payload.topics,
        notes=payload.notes, demo_presented=payload.demo_presented, status=payload.status,
        next_steps=payload.next_steps, follow_up_due_at=payload.follow_up_due_at, created_by=user.id,
    )
    if item.status in {"confirmed", "completed"}:
        interaction.status = "meeting"
    db.add(item)
    db.flush()
    db.add(AuditLog(user_id=user.id, action="meeting_recorded", entity_type="meeting", entity_id=str(item.id), metadata_json={"status": item.status, "lead_id": str(lead.id)}))
    db.commit()
    return _meeting_json(item, db)


@router.patch("/meetings/{meeting_id}")
def update_meeting(meeting_id: uuid.UUID, payload: MeetingPatch, db: Session = Depends(get_db), user: User = Depends(require_roles(*STAFF))):
    item = db.get(Meeting, meeting_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Meeting not found.")
    if user.role == "SALES" and item.employee_id not in (None, user.id):
        raise HTTPException(status_code=403, detail="You can update meetings assigned to you.")
    if payload.employee_id is not None:
        employee = db.get(User, payload.employee_id)
        if employee is None or not employee.is_active:
            raise HTTPException(status_code=422, detail="Choose an active team member.")
    if user.role == "SALES" and payload.employee_id not in (None, user.id):
        raise HTTPException(status_code=403, detail="You can assign the meeting only to yourself.")
    for key in payload.model_fields_set:
        setattr(item, key, getattr(payload, key))
    if payload.status in {"confirmed", "completed"} and item.interaction_id:
        interaction = db.get(Interaction, item.interaction_id)
        if interaction:
            interaction.status = "meeting"
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
    }, exclude_registrant_identity=registrant_identity_key(registrant))


@router.post("/events/{event_id}/research/registrants/{registrant_id}/match")
def match_registrant(event_id: uuid.UUID, registrant_id: uuid.UUID, payload: RegistrantMatchInput, db: Session = Depends(get_db), user: User = Depends(require_roles(*MANAGERS))):
    registrant = db.scalar(select(EventRegistrant).where(EventRegistrant.id == registrant_id, EventRegistrant.event_id == event_id))
    lead = db.get(Lead, payload.lead_id)
    if registrant is None or lead is None:
        raise HTTPException(status_code=404, detail="Research registrant or lead not found.")
    if not db.scalar(select(Interaction.id).where(
        Interaction.lead_id == lead.id, Interaction.event_id == event_id,
    )):
        raise HTTPException(status_code=422, detail="The lead has no captured interaction in this event.")
    matched_rows = mark_registrant_identity_matched(db, registrant, lead.id)
    db.add(AuditLog(user_id=user.id, action="research_registrant_matched", entity_type="event_registrant", entity_id=str(registrant.id), metadata_json={"lead_id": str(lead.id)}))
    db.commit()
    return {"id": str(registrant.id), "matched_lead_id": str(lead.id), "match_status": "matched", "matched_source_rows": matched_rows}
