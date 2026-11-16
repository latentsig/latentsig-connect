import re
import hashlib
import uuid
from difflib import SequenceMatcher

import phonenumbers
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AuditLog, BusinessCard, Event, EventRegistrant, EventSession, IntegrationJob, Interaction, Lead, now_utc
from app.schemas.lead import LeadSubmission
from app.services.storage.business_cards import StagedUploadMissing, storage


def normalize_phone(raw: str) -> tuple[str, str | None]:
    try:
        parsed = phonenumbers.parse(raw, settings.default_phone_region)
    except phonenumbers.NumberParseException:
        raise HTTPException(status_code=422, detail="Choose a country and enter a valid phone number.") from None
    if not phonenumbers.is_valid_number(parsed):
        raise HTTPException(status_code=422, detail="Choose a country and enter a valid phone number.")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164), phonenumbers.region_code_for_number(parsed)


def _lead_code(event: Event | None) -> str:
    if event is None:
        return f"LS-DIRECT-{uuid.uuid4().hex[:10].upper()}"
    prefix = re.sub(r"[^A-Za-z0-9]+", "-", event.slug).strip("-").upper()
    if len(prefix) > 22:
        prefix = f"{prefix[:17].rstrip('-')}-{hashlib.sha1(event.slug.encode()).hexdigest()[:4].upper()}"
    next_number = event.next_lead_number
    event.next_lead_number = next_number + 1
    return f"LS-{prefix}-{next_number:06d}"


def _idempotent_result(db: Session, key: str) -> dict[str, str | bool] | None:
    interaction = db.scalar(select(Interaction).where(Interaction.idempotency_key == key))
    if interaction is None:
        return None
    lead = db.get(Lead, interaction.lead_id)
    if lead is None:
        return None
    return {"id": str(lead.id), "lead_code": lead.lead_code, "interaction_id": str(interaction.id), "created": bool(interaction.submission_created)}


def link_event_research_registrants(db: Session, event: Event, lead: Lead) -> None:
    email = (lead.normalized_email or "").strip().casefold()
    phone_digits = re.sub(r"\D", "", lead.normalized_phone or "")
    name = re.sub(r"[^a-z0-9]", "", (lead.full_name or "").casefold())
    company = re.sub(r"[^a-z0-9]", "", (lead.company or "").casefold())
    clauses = []
    if email:
        clauses.append(func.lower(func.trim(EventRegistrant.email)) == email)
    if phone_digits:
        normalized_source_phone = EventRegistrant.phone
        for character in ("+", " ", "-", "(", ")", ".", "/"):
            normalized_source_phone = func.replace(normalized_source_phone, character, "")
        clauses.append(normalized_source_phone == phone_digits)
    name_token = next(iter(re.findall(r"[a-z0-9]+", (lead.full_name or "").casefold())), "")
    company_token = next(iter(re.findall(r"[a-z0-9]+", (lead.company or "").casefold())), "")
    if name_token and company_token:
        clauses.append((EventRegistrant.full_name.ilike(f"%{name_token}%")) & EventRegistrant.company.ilike(f"%{company_token}%"))
    if not clauses:
        return
    candidates = db.scalars(select(EventRegistrant).where(EventRegistrant.event_id == event.id, or_(*clauses)).limit(5000)).all()
    high: list[EventRegistrant] = []
    possible: list[EventRegistrant] = []
    for registrant in candidates:
        same_email = bool(email and registrant.email and email == registrant.email.strip().casefold())
        same_phone = bool(phone_digits and registrant.phone and phone_digits == re.sub(r"\D", "", registrant.phone))
        candidate_name = re.sub(r"[^a-z0-9]", "", (registrant.full_name or "").casefold())
        candidate_company = re.sub(r"[^a-z0-9]", "", (registrant.company or "").casefold())
        same_name_company = bool(name and company and name == candidate_name and company == candidate_company)
        name_score = SequenceMatcher(None, name, candidate_name).ratio() if name and candidate_name else 0
        company_score = SequenceMatcher(None, company, candidate_company).ratio() if company and candidate_company else 0
        if same_email or same_phone or same_name_company:
            high.append(registrant)
        elif name_score >= 0.90 and company_score >= 0.88:
            possible.append(registrant)
    if len(high) == 1:
        registrant = high[0]
        if registrant.matched_lead_id in (None, lead.id):
            registrant.matched_lead_id = lead.id
            registrant.match_status = "matched"
        else:
            registrant.match_status = "suggested"
    elif high or possible:
        for registrant in [*high, *possible]:
            if registrant.matched_lead_id != lead.id:
                registrant.match_status = "suggested"


def create_lead_submission(db: Session, payload: LeadSubmission, idempotency_key: str | None = None) -> dict[str, str | bool]:
    if idempotency_key:
        previous = _idempotent_result(db, idempotency_key)
        if previous:
            return previous
    card_tokens = {"front": payload.business_card_token, "back": payload.business_card_back_token}
    if payload.capture_method == "business_card" and not card_tokens["front"]:
        raise HTTPException(status_code=422, detail="Please scan your business card again before submitting.")
    if payload.capture_method != "business_card" and any(card_tokens.values()):
        raise HTTPException(status_code=422, detail="Business-card images can only be submitted with the card-review flow.")
    phone, phone_country = normalize_phone(payload.phone)
    email = str(payload.email).strip().lower()
    event = None
    session = None
    if payload.event_slug:
        event = db.scalar(select(Event).where(Event.slug == payload.event_slug, Event.is_active.is_(True)).with_for_update())
        if event is None:
            raise HTTPException(status_code=422, detail="This event link is not active. Please ask the LatentSig team for help.")
    if payload.session_slug:
        if event is None:
            raise HTTPException(status_code=422, detail="Choose an event before selecting one of its sessions.")
        session = db.scalar(select(EventSession).where(
            EventSession.event_id == event.id,
            EventSession.slug == payload.session_slug,
            EventSession.is_active.is_(True),
        ))
        if session is None:
            raise HTTPException(status_code=422, detail="This event session is not active. Please ask the LatentSig team for help.")

    lead = db.scalar(select(Lead).where(Lead.normalized_email == email)) if email else None
    if lead is None and phone:
        lead = db.scalar(select(Lead).where(Lead.normalized_phone == phone))
    created = lead is None
    if lead is None:
        lead = Lead(
            lead_code=_lead_code(event), full_name=payload.full_name, company=payload.company,
            job_title=payload.job_title, email=str(payload.email), email_type=payload.email_type,
            normalized_email=email, phone=phone, normalized_phone=phone, website=payload.website, address=payload.address,
            country=phone_country,
        )
        db.add(lead)
        db.flush()
    else:
        # Keep the canonical lead current while preserving each event as an interaction.
        lead.full_name = payload.full_name
        lead.company = payload.company
        lead.job_title = payload.job_title
        lead.email = str(payload.email)
        lead.email_type = payload.email_type
        lead.phone = phone
        lead.normalized_email = email
        lead.normalized_phone = phone
        lead.country = phone_country
        lead.website = payload.website or lead.website
        lead.address = payload.address or lead.address

    interaction = Interaction(
        lead_id=lead.id, event_id=event.id if event else None, session_id=session.id if session else None,
        interest=payload.interest, intent=payload.intent,
        other_interest_details=payload.other_interest_details, other_intent_details=payload.other_intent_details,
        requirement_message=payload.requirement_message, capture_method=payload.capture_method,
        data_processing_consent_at=now_utc(),
        follow_up_consent_at=now_utc() if payload.follow_up_consent else None,
        consent_notice_version=settings.consent_notice_version,
        idempotency_key=idempotency_key, submission_created=created,
        source=payload.source, captured_by=payload.captured_by or payload.source,
        utm_source=payload.utm_source, utm_medium=payload.utm_medium,
        utm_campaign=payload.utm_campaign, status="new",
    )
    if event:
        link_event_research_registrants(db, event, lead)
    db.add(interaction)
    db.flush()

    attached_storage_paths: list[str] = []
    staged_metadata: dict[str, dict[str, str]] = {}
    for side, token in card_tokens.items():
        if not token:
            continue
        try:
            storage.staging_path(token)
            staged_metadata[side] = storage.metadata(token)
        except StagedUploadMissing:
            raise HTTPException(status_code=422, detail=f"The {side} image expired. Please upload the card again.") from None
    front_metadata = staged_metadata.get("front", {})
    if payload.capture_method == "business_card":
        raw_consent_at = front_metadata.get("ai_processing_consent_at")
        consent_version = front_metadata.get("ai_processing_consent_notice_version")
        if not raw_consent_at or consent_version != settings.consent_notice_version:
            raise HTTPException(status_code=422, detail="Card scanning consent was not recorded for the current notice. Please scan the card again.")
        from datetime import datetime
        interaction.ai_processing_consent_at = datetime.fromisoformat(raw_consent_at)
        interaction.ai_processing_consent_notice_version = consent_version
    front_storage_path = back_storage_path = None
    front_file_size = back_file_size = None
    try:
        for side, token in card_tokens.items():
            if not token:
                continue
            metadata = staged_metadata[side]
            path, size = storage.attach(token, event.slug if event else "unattributed", lead.lead_code, metadata["mime_type"])
            attached_storage_paths.append(path)
            if side == "front":
                front_storage_path, front_file_size = path, size
            else:
                back_storage_path, back_file_size = path, size

        if front_storage_path:
            ocr = dict(payload.business_card_ocr or {})
            ocr.pop("business_card_token", None)
            ocr.pop("business_card_tokens", None)
            db.add(BusinessCard(
                lead_id=lead.id, interaction_id=interaction.id,
                storage_path=front_storage_path, original_filename=staged_metadata["front"]["filename"],
                mime_type=staged_metadata["front"]["mime_type"], file_size=front_file_size or 0,
                back_storage_path=back_storage_path,
                back_original_filename=staged_metadata.get("back", {}).get("filename"),
                back_mime_type=staged_metadata.get("back", {}).get("mime_type"),
                back_file_size=back_file_size, ocr_text=str(ocr.get("ocr_text", ""))[:20000], ocr_json=ocr,
            ))
    except Exception:
        for path in attached_storage_paths:
            storage.delete(path)
        raise

    db.add(AuditLog(action="lead_captured", entity_type="lead", entity_id=str(lead.id), metadata_json={"interaction_id": str(interaction.id), "capture_method": payload.capture_method}))
    if settings.google_sheet_id:
        db.add(IntegrationJob(type="google_sheets_upsert", entity_id=interaction.id, status="pending"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        for path in attached_storage_paths:
            storage.delete(path)
        if idempotency_key:
            previous = _idempotent_result(db, idempotency_key)
            if previous:
                return previous
        raise HTTPException(status_code=409, detail="This contact changed while it was being saved. Please submit once more.") from None
    except Exception:
        db.rollback()
        for path in attached_storage_paths:
            storage.delete(path)
        raise
    return {"id": str(lead.id), "lead_code": lead.lead_code, "interaction_id": str(interaction.id), "created": created}
