import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.security import require_roles
from app.db.models import AuditLog, BusinessCard, Event, EventRegistrant, EventSession, EventStaff, Interaction, Lead, StaffCardCapture, User, now_utc
from app.db.session import get_db
from app.services.leads.service import _lead_code, normalize_phone
from app.services.ocr.preprocess import InvalidImage, decode_and_prepare, detect_image_mime
from app.services.research_matching import find_attendee_candidates, mark_registrant_identity_matched, registrant_identity_rows
from app.services.storage.business_cards import storage
from app.services.vision.client import extract_card
from app.services.vision.exceptions import VisionConfigurationError, VisionUnavailable

router = APIRouter(prefix="/admin", tags=["staff card capture"])
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
STAFF_ROLES = ("ADMIN", "MANAGER", "SALES")
EDITABLE_FIELDS = {"full_name", "company", "job_title", "email", "phone", "website", "address"}


class CaptureFields(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    full_name: str | None = Field(default=None, max_length=180)
    company: str | None = Field(default=None, max_length=180)
    job_title: str | None = Field(default=None, max_length=180)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=80)
    website: str | None = Field(default=None, max_length=500)
    address: str | None = Field(default=None, max_length=500)


class CaptureReviewInput(BaseModel):
    fields: CaptureFields = Field(default_factory=CaptureFields)
    lead_id: uuid.UUID | None = None
    registrant_id: uuid.UUID | None = None
    details_verified: bool = False
    create_new_confirmed: bool = False


def _event_for_capture(db: Session, event_id: uuid.UUID | None) -> Event | None:
    if event_id is None:
        return None
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=422, detail="Choose an event that still exists.")
    return event


def _field_value(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _normal_email(value: str | None) -> str | None:
    value = _field_value(value)
    if value is None:
        return None
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        return None
    return value.casefold()


def _safe_card_fields(extraction: dict) -> dict[str, str | None]:
    values: dict[str, str | None] = {}
    for key in EDITABLE_FIELDS:
        item = extraction.get(key)
        if isinstance(item, dict):
            item = item.get("value")
        values[key] = _field_value(item if isinstance(item, str) else None)
    values["email"] = values["email"] if _normal_email(values["email"]) else None
    if values["website"] and not values["website"].startswith(("https://", "http://")):
        values["website"] = f"https://{values['website']}"
    return values


def _person_candidates(db: Session, event_id: uuid.UUID | None, fields: dict) -> tuple[Lead | None, EventRegistrant | None, list[dict]]:
    candidates = find_attendee_candidates(db, event_id, fields)
    high = [candidate for candidate in candidates if candidate["confidence"] == "high"]
    if len(high) == 1:
        selected = high[0]
        if selected["kind"] == "lead":
            return db.get(Lead, uuid.UUID(selected["id"])), None, candidates
        registrant = db.get(EventRegistrant, uuid.UUID(selected["id"]))
        matched_lead = db.get(Lead, registrant.matched_lead_id) if registrant and registrant.matched_lead_id else None
        return matched_lead, registrant, candidates
    return None, None, candidates


def _attach_capture_to_lead(db: Session, capture: StaffCardCapture, lead: Lead, user: User, event: Event | None, session: EventSession | None, extraction: dict) -> Interaction:
    interaction = Interaction(
        lead_id=lead.id, event_id=event.id if event else None, session_id=session.id if session else None,
        interest=[], intent="Unspecified", capture_method="staff_business_card", source="staff_quick_capture",
        captured_by=user.full_name, captured_by_user_id=user.id, data_processing_consent_at=None,
        follow_up_consent_at=None, consent_notice_version=None,
        ai_processing_consent_at=capture.external_ai_consent_at,
        ai_processing_consent_notice_version=capture.external_ai_consent_notice_version,
        status="pending_review", synthetic_test=capture.synthetic_test,
        exclude_from_analytics=capture.exclude_from_analytics,
    )
    db.add(interaction)
    db.flush()
    db.add(BusinessCard(
        lead_id=lead.id, interaction_id=interaction.id, storage_path=capture.storage_path,
        original_filename=capture.original_filename, mime_type=capture.mime_type,
        file_size=capture.file_size, ocr_json=extraction,
    ))
    capture.lead_id = lead.id
    capture.interaction_id = interaction.id
    capture.status = "linked"
    return interaction


def _make_lead(db: Session, event: Event | None, fields: dict[str, str | None]) -> Lead:
    email = fields.get("email")
    normalized_email = _normal_email(email)
    phone, country = None, None
    if fields.get("phone"):
        try:
            phone, country = normalize_phone(fields["phone"])
        except HTTPException:
            fields["phone"] = None
    lead = Lead(
        lead_code=_lead_code(event), full_name=fields.get("full_name"), company=fields.get("company"),
        job_title=fields.get("job_title"), email=email if normalized_email else None,
        email_type="work", normalized_email=normalized_email,
        phone=phone, normalized_phone=phone, country=country,
        website=fields.get("website"), address=fields.get("address"),
    )
    db.add(lead)
    db.flush()
    return lead


def _capture_json(capture: StaffCardCapture, db: Session) -> dict:
    event = db.get(Event, capture.event_id) if capture.event_id else None
    staff = db.get(User, capture.captured_by_user_id) if capture.captured_by_user_id else None
    lead = db.get(Lead, capture.lead_id) if capture.lead_id else None
    candidates = []
    fields = _safe_card_fields(capture.ocr_json or {})
    if capture.status == "pending_match":
        candidates = find_attendee_candidates(db, capture.event_id, fields)
    return {
        "id": str(capture.id), "event_id": str(capture.event_id) if capture.event_id else None,
        "session_id": str(capture.session_id) if capture.session_id else None,
        "event_name": event.name if event else None, "event_slug": event.slug if event else None,
        "captured_by_user_id": str(capture.captured_by_user_id) if capture.captured_by_user_id else None,
        "captured_by": staff.full_name if staff else None, "lead_id": str(capture.lead_id) if capture.lead_id else None,
        "lead_name": lead.full_name if lead else None, "interaction_id": str(capture.interaction_id) if capture.interaction_id else None,
        "original_filename": capture.original_filename, "mime_type": capture.mime_type, "file_size": capture.file_size,
        "ocr": capture.ocr_json, "status": capture.status, "error": capture.error,
        "synthetic_test": capture.synthetic_test, "exclude_from_analytics": capture.exclude_from_analytics,
        "external_ai_consent_recorded": capture.external_ai_consent_at is not None,
        "created_at": capture.created_at.isoformat(), "candidates": candidates,
    }


def _authorize_capture_review(capture: StaffCardCapture, db: Session, user: User) -> None:
    if user.role in {"ADMIN", "MANAGER"}:
        return
    if capture.captured_by_user_id == user.id:
        return
    if capture.event_id and db.scalar(select(EventStaff.id).where(EventStaff.event_id == capture.event_id, EventStaff.user_id == user.id)):
        return
    raise HTTPException(status_code=404, detail="Card capture not found.")


@router.get("/card-capture-policy")
def card_capture_policy(user: User = Depends(require_roles(*STAFF_ROLES))):
    return {
        "ocr_enabled": settings.ocr_enabled,
        "provider": settings.ocr_provider.lower(),
        "external_ai_requires_consent": settings.ocr_provider.lower() in {"openrouter", "vertex"},
        "staff_card_processing_rules_approved": settings.staff_card_processing_rules_approved,
        "external_ai_consent_notice_version": settings.staff_card_external_ai_consent_notice_version,
    }


@router.post("/card-captures", status_code=201)
async def create_card_capture(
    file: UploadFile = File(...), event_id: uuid.UUID | None = Form(default=None),
    session_id: uuid.UUID | None = Form(default=None), external_ai_consent: bool = Form(default=False),
    synthetic_test: bool = Form(default=False), db: Session = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
):
    event = _event_for_capture(db, event_id)
    if event and not event.is_active:
        raise HTTPException(status_code=422, detail="Choose an active event for a new card capture.")
    if user.role == "SALES" and event and not db.scalar(select(EventStaff.id).where(EventStaff.event_id == event.id, EventStaff.user_id == user.id)):
        raise HTTPException(status_code=403, detail="You are not assigned to capture leads for this event.")
    session = db.get(EventSession, session_id) if session_id else None
    if session_id and (session is None or event is None or session.event_id != event.id or not session.is_active):
        raise HTTPException(status_code=422, detail="Choose an active session belonging to the selected event.")
    if synthetic_test and user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Only an administrator can mark a card as a synthetic test.")
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=415, detail="Upload a JPG, PNG, or WEBP business-card image.")
    data = await file.read(settings.max_upload_bytes + 1)
    await file.close()
    if not data or len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Choose a non-empty card image no larger than 10 MB.")
    mime_type = detect_image_mime(data)
    if mime_type != file.content_type:
        raise HTTPException(status_code=415, detail="The image contents do not match its file type.")
    try:
        prepared = await run_in_threadpool(decode_and_prepare, data)
    except InvalidImage as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    provider = settings.ocr_provider.lower()
    external_provider = provider in {"openrouter", "vertex"}
    if synthetic_test and external_ai_consent:
        raise HTTPException(status_code=422, detail="Synthetic captures cannot record visitor AI consent.")
    if external_ai_consent and not external_provider:
        raise HTTPException(status_code=422, detail="Visitor AI consent only applies when an external OCR provider is configured.")
    if external_ai_consent and not settings.staff_card_processing_rules_approved:
        raise HTTPException(status_code=403, detail="Staff card processing rules are not approved for external AI processing.")
    should_extract = settings.ocr_enabled and (
        provider == "ollama"
        or (external_provider and settings.staff_card_processing_rules_approved and (synthetic_test or external_ai_consent))
    )

    extraction: dict = {}
    capture_status = "pending_review"
    error = None
    external_consent_at = None
    external_consent_version = None
    if should_extract:
        try:
            result = await run_in_threadpool(extract_card, [(prepared, "image/jpeg")])
            extraction = result.model_dump()
            if result.is_template:
                capture_status = "template_detected"
            elif not any(getattr(result, name) for name in EDITABLE_FIELDS):
                capture_status = "ocr_failed"
                error = "No readable contact details were returned. Review the card and enter the visible details manually."
            if external_provider and external_ai_consent:
                external_consent_at = now_utc()
                external_consent_version = settings.staff_card_external_ai_consent_notice_version
        except (VisionConfigurationError, VisionUnavailable):
            capture_status = "ocr_failed"
            error = "OCR could not complete. The original card was saved; review it and enter details manually or retry later."
        except Exception:
            capture_status = "ocr_failed"
            error = "OCR could not complete. The original card was saved; review it and enter details manually or retry later."
    elif external_provider:
        error = "External OCR was skipped because the approved processing rule and visitor authorization were not recorded. The image remains private for manual review."
    elif not settings.ocr_enabled:
        error = "OCR is disabled. The image remains private for manual review."

    filename = Path(file.filename or "business-card").name[:255]
    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[mime_type]
    storage_path, file_size = storage.save_private(data, event.slug if event else "unattributed", "staff-card-captures", suffix, mime_type)
    capture = StaffCardCapture(
        event_id=event.id if event else None, session_id=session.id if session else None,
        captured_by_user_id=user.id,
        original_filename=filename, mime_type=mime_type, file_size=file_size,
        storage_path=storage_path, ocr_json=extraction, status=capture_status, error=error,
        synthetic_test=synthetic_test, exclude_from_analytics=synthetic_test,
        external_ai_consent_at=external_consent_at,
        external_ai_consent_notice_version=external_consent_version,
    )
    db.add(capture)
    db.flush()
    candidates: list[dict] = []
    fields = _safe_card_fields(extraction)
    extracted_anything = any(fields.values())
    if capture_status not in {"template_detected", "ocr_failed"} and extracted_anything:
        if synthetic_test:
            lead = _make_lead(db, event, fields)
            _attach_capture_to_lead(db, capture, lead, user, event, session, extraction)
        else:
            matched_lead, matched_registrant, candidates = _person_candidates(db, event.id if event else None, fields)
            high_candidates = [item for item in candidates if item["confidence"] == "high"]
            if len(high_candidates) > 1 or (candidates and not high_candidates):
                capture.status = "pending_match"
            else:
                if matched_lead is None:
                    lead = _make_lead(db, event, fields)
                    if matched_registrant:
                        mark_registrant_identity_matched(db, matched_registrant, lead.id)
                else:
                    lead = matched_lead
                _attach_capture_to_lead(db, capture, lead, user, event, session, extraction)
    db.add(AuditLog(user_id=user.id, action="staff_card_captured", entity_type="staff_card_capture", entity_id=str(capture.id), metadata_json={
        "event_id": str(event.id) if event else None, "status": capture.status,
        "synthetic_test": synthetic_test, "ocr_provider": provider if should_extract else "not_used",
    }))
    try:
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(storage_path)
        raise
    return {**_capture_json(capture, db), "candidates": candidates}


@router.get("/card-captures")
def search_card_captures(
    search: str | None = None, event_id: uuid.UUID | None = None, status: str | None = None,
    include_synthetic: bool = False, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db), user: User = Depends(require_roles(*STAFF_ROLES)),
):
    query = select(StaffCardCapture)
    if user.role == "SALES":
        query = query.where(or_(StaffCardCapture.captured_by_user_id == user.id, StaffCardCapture.lead_id.in_(
            select(Interaction.lead_id).where(Interaction.assigned_to == user.id)
        )))
    if event_id:
        query = query.where(StaffCardCapture.event_id == event_id)
    if status:
        query = query.where(StaffCardCapture.status == status)
    if not include_synthetic:
        query = query.where(StaffCardCapture.synthetic_test.is_(False))
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(
            StaffCardCapture.original_filename.ilike(term), cast(StaffCardCapture.ocr_json, String).ilike(term),
        ))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(StaffCardCapture.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_capture_json(item, db) for item in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/card-captures/{capture_id}")
def get_card_capture(capture_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_roles(*STAFF_ROLES))):
    capture = db.get(StaffCardCapture, capture_id)
    if capture is None:
        raise HTTPException(status_code=404, detail="Card capture not found.")
    _authorize_capture_review(capture, db, user)
    return _capture_json(capture, db)


@router.get("/card-captures/{capture_id}/image")
def get_card_capture_image(capture_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_roles(*STAFF_ROLES))):
    capture = db.get(StaffCardCapture, capture_id)
    if capture is None:
        raise HTTPException(status_code=404, detail="Card capture not found.")
    _authorize_capture_review(capture, db, user)
    try:
        content = storage.read(capture.storage_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="The private card image is unavailable.") from None
    return Response(content, media_type=capture.mime_type, headers={
        "Content-Disposition": "inline", "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
    })


@router.post("/card-captures/{capture_id}/resolve")
def resolve_card_capture(capture_id: uuid.UUID, payload: CaptureReviewInput, db: Session = Depends(get_db), user: User = Depends(require_roles(*STAFF_ROLES))):
    capture = db.get(StaffCardCapture, capture_id)
    if capture is None:
        raise HTTPException(status_code=404, detail="Card capture not found.")
    _authorize_capture_review(capture, db, user)
    event = _event_for_capture(db, capture.event_id)
    session = db.get(EventSession, capture.session_id) if capture.session_id else None
    fields = _safe_card_fields(capture.ocr_json or {})
    for key in payload.fields.model_fields_set:
        fields[key] = _field_value(getattr(payload.fields, key))
    if fields.get("email") and not _normal_email(fields["email"]):
        raise HTTPException(status_code=422, detail="Enter a valid email address or leave it blank.")
    if fields.get("phone"):
        try:
            normalize_phone(fields["phone"])
        except HTTPException:
            raise HTTPException(status_code=422, detail="Enter a valid phone number or leave it blank.") from None
    if (capture.ocr_json or {}).get("is_template") and not payload.details_verified:
        raise HTTPException(status_code=422, detail="This image was detected as a template. Confirm the identity details manually before saving a lead.")
    if payload.lead_id and payload.registrant_id:
        raise HTTPException(status_code=422, detail="Choose one existing record to link this card capture.")
    if payload.lead_id:
        lead = db.get(Lead, payload.lead_id)
        if lead is None:
            raise HTTPException(status_code=404, detail="Selected lead not found.")
        if capture.lead_id and capture.lead_id != lead.id and capture.interaction_id:
            interaction = db.get(Interaction, capture.interaction_id)
            if interaction:
                interaction.lead_id = lead.id
            card = db.scalar(select(BusinessCard).where(BusinessCard.interaction_id == capture.interaction_id))
            if card:
                card.lead_id = lead.id
        capture.lead_id = lead.id
    elif payload.registrant_id:
        registrant = db.scalar(select(EventRegistrant).where(EventRegistrant.id == payload.registrant_id, EventRegistrant.event_id == capture.event_id))
        if registrant is None:
            raise HTTPException(status_code=404, detail="Selected research registrant not found for this event.")
        linked_lead_ids = {row.matched_lead_id for row in registrant_identity_rows(db, registrant.event_id, registrant) if row.matched_lead_id}
        if len(linked_lead_ids) > 1:
            raise HTTPException(status_code=409, detail="This research profile is linked to multiple leads. Choose a lead directly and reconcile the research records.")
        lead = db.get(Lead, next(iter(linked_lead_ids))) if linked_lead_ids else None
        if lead is None:
            if not fields.get("full_name"):
                raise HTTPException(status_code=422, detail="Enter the person's name before linking the research record.")
            lead = _make_lead(db, event, fields)
        mark_registrant_identity_matched(db, registrant, lead.id)
    else:
        lead = db.get(Lead, capture.lead_id) if capture.lead_id else None
        if lead is None:
            if not fields.get("full_name"):
                raise HTTPException(status_code=422, detail="Enter the person's name before saving this card as a lead.")
            candidates = find_attendee_candidates(db, capture.event_id, fields)
            if candidates and not payload.create_new_confirmed:
                raise HTTPException(status_code=409, detail="Possible duplicate records need review. Select an existing lead or confirm a new record.")
            lead = _make_lead(db, event, fields)
    if capture.interaction_id:
        interaction = db.get(Interaction, capture.interaction_id)
        if interaction:
            interaction.lead_id = lead.id
        card = db.scalar(select(BusinessCard).where(BusinessCard.interaction_id == capture.interaction_id))
        if card:
            card.lead_id = lead.id
    else:
        _attach_capture_to_lead(db, capture, lead, user, event, session, capture.ocr_json or {})
    for key, value in fields.items():
        if value is not None:
            if key == "email":
                lead.email = value
                lead.normalized_email = _normal_email(value)
            elif key == "phone":
                phone, country = normalize_phone(value)
                lead.phone, lead.normalized_phone, lead.country = phone, phone, country
            else:
                setattr(lead, key, value)
    capture.lead_id = lead.id
    capture.status = "linked"
    capture.error = None
    db.add(AuditLog(user_id=user.id, action="staff_card_reviewed", entity_type="staff_card_capture", entity_id=str(capture.id), metadata_json={"lead_id": str(lead.id)}))
    db.commit()
    return _capture_json(capture, db)


@router.delete("/card-captures/{capture_id}", status_code=204)
def delete_synthetic_card_capture(capture_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_roles("ADMIN"))):
    capture = db.get(StaffCardCapture, capture_id)
    if capture is None:
        raise HTTPException(status_code=404, detail="Card capture not found.")
    if not capture.synthetic_test or not capture.exclude_from_analytics:
        raise HTTPException(status_code=409, detail="Only explicitly marked synthetic test captures can be removed through test cleanup.")
    path = capture.storage_path
    lead = db.get(Lead, capture.lead_id) if capture.lead_id else None
    if capture.interaction_id:
        interaction = db.get(Interaction, capture.interaction_id)
        if interaction:
            db.delete(interaction)
            if lead and db.scalar(select(func.count(Interaction.id)).where(Interaction.lead_id == lead.id, Interaction.id != interaction.id)) == 0:
                db.delete(lead)
    db.delete(capture)
    db.add(AuditLog(user_id=user.id, action="synthetic_card_capture_deleted", entity_type="staff_card_capture", entity_id=str(capture_id), metadata_json={}))
    db.commit()
    storage.delete(path)
