import re
import hashlib

import phonenumbers
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AuditLog, BusinessCard, Event, IntegrationJob, Interaction, Lead
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


def _lead_code(event: Event) -> str:
    prefix = re.sub(r"[^A-Za-z0-9]+", "-", event.slug).strip("-").upper()
    if len(prefix) > 22:
        prefix = f"{prefix[:17].rstrip('-')}-{hashlib.sha1(event.slug.encode()).hexdigest()[:4].upper()}"
    next_number = event.next_lead_number
    event.next_lead_number = next_number + 1
    return f"LS-{prefix}-{next_number:06d}"


def create_lead_submission(db: Session, payload: LeadSubmission) -> dict[str, str | bool]:
    card_tokens = {"front": payload.business_card_token, "back": payload.business_card_back_token}
    if payload.capture_method == "business_card" and not card_tokens["front"]:
        raise HTTPException(status_code=422, detail="Please scan your business card again before submitting.")
    if payload.capture_method != "business_card" and any(card_tokens.values()):
        raise HTTPException(status_code=422, detail="Business-card images can only be submitted with the card-review flow.")
    phone, phone_country = normalize_phone(payload.phone)
    email = str(payload.email).strip().lower()
    event_slug = payload.event_slug or settings.default_event_slug
    event = db.scalar(select(Event).where(Event.slug == event_slug, Event.is_active.is_(True)).with_for_update())
    if event is None:
        raise HTTPException(status_code=422, detail="This event link is not active. Please ask the LatentSig team for help.")

    lead = db.scalar(select(Lead).where(Lead.normalized_email == email))
    if lead is None:
        lead = db.scalar(select(Lead).where(Lead.normalized_phone == phone))
    created = lead is None
    if lead is None:
        lead = Lead(
            lead_code=_lead_code(event), full_name=payload.full_name, company=payload.company,
            job_title=payload.job_title, email=str(payload.email), email_type=payload.email_type,
            normalized_email=email, phone=phone, normalized_phone=phone, website=payload.website,
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

    interaction = Interaction(
        lead_id=lead.id, event_id=event.id, interest=payload.interest, intent=payload.intent,
        other_interest_details=payload.other_interest_details, other_intent_details=payload.other_intent_details,
        requirement_message=payload.requirement_message, capture_method=payload.capture_method,
        source=payload.source, captured_by=payload.captured_by or payload.source,
        utm_source=payload.utm_source, utm_medium=payload.utm_medium,
        utm_campaign=payload.utm_campaign, status="new",
    )
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
    front_storage_path = back_storage_path = None
    front_file_size = back_file_size = None
    try:
        for side, token in card_tokens.items():
            if not token:
                continue
            metadata = staged_metadata[side]
            path, size = storage.attach(token, event.slug, lead.lead_code, metadata["mime_type"])
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
        raise HTTPException(status_code=409, detail="This contact changed while it was being saved. Please submit once more.") from None
    except Exception:
        db.rollback()
        for path in attached_storage_paths:
            storage.delete(path)
        raise
    return {"id": str(lead.id), "lead_code": lead.lead_code, "interaction_id": str(interaction.id), "created": created}
