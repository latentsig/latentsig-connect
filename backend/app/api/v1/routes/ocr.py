import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.rate_limit import rate_limit
from app.services.ocr.preprocess import InvalidImage, decode_and_prepare, detect_image_mime
from app.services.storage.business_cards import storage
from app.services.vision.client import extract_card
from app.services.vision.exceptions import VisionConfigurationError, VisionUnavailable

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ocr", tags=["ocr"])
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _field(value: str | None, confidence: float = 0.0) -> dict[str, object]:
    return {"value": value or "", "confidence": confidence if value else 0.0}


def _extract(images: list[tuple[bytes, str]]) -> dict[str, object]:
    result = extract_card(images)
    email = result.email or ""
    email_type = "personal" if email.rsplit("@", 1)[-1].lower() in {
        "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "live.com", "icloud.com", "proton.me",
    } else "work"
    phone = result.phone or ""
    return {
        "full_name": _field(result.full_name, 0.75), "company": _field(result.company, 0.75),
        "job_title": _field(result.job_title, 0.75), "email": _field(email, 0.8),
        "email_type": _field(email_type if email else "work", 0.8 if email else 0),
        "email_candidates": ([{"value": email, "type": email_type}] if email else []),
        "phone": _field(phone, 0.75), "phone_country": {"value": "", "name": "", "calling_code": "", "confidence": 0},
        "website": _field(result.website, 0.75), "address": _field(result.address, 0.75),
        "candidates": {"emails": [email] if email else [], "phones": [phone] if phone else [], "websites": [result.website] if result.website else []},
        "ocr_text": "", "text_blocks": [], "is_template": result.is_template,
        "warnings": result.warnings, "uncertain_fields": result.uncertain_fields,
    }


@router.post("/business-card", dependencies=[Depends(rate_limit("ocr"))])
async def read_business_card(files: list[UploadFile] = File(default=[]), file: UploadFile | None = File(default=None), ai_processing_consent: bool = Form(default=False)):
    uploads = files or ([file] if file else [])
    if not uploads:
        raise HTTPException(status_code=400, detail="Choose the front of your business card first.")
    if len(uploads) > 2:
        raise HTTPException(status_code=413, detail="Upload one or two images: the front and optional back of the card.")
    data_by_side: list[tuple[str, UploadFile, bytes, str]] = []
    total_size = 0
    staged_tokens: list[str] = []
    try:
        for index, upload in enumerate(uploads):
            if upload.content_type not in ALLOWED_MIME_TYPES:
                raise HTTPException(status_code=415, detail="Upload JPG, PNG, or WEBP images.")
            data = await upload.read(settings.max_upload_bytes + 1)
            if len(data) > settings.max_upload_bytes:
                raise HTTPException(status_code=413, detail="Each business-card image must be 10 MB or smaller.")
            if not data:
                raise HTTPException(status_code=400, detail="One of the selected card images is empty.")
            total_size += len(data)
            if total_size > 2 * settings.max_upload_bytes:
                raise HTTPException(status_code=413, detail="The front and back images must total 20 MB or less.")
            mime_type = detect_image_mime(data)
            if mime_type != upload.content_type:
                raise HTTPException(status_code=415, detail="An image's contents do not match its selected file type.")
            side = "front" if index == 0 else "back"
            data_by_side.append((side, upload, data, mime_type))
        if not ai_processing_consent:
            raise HTTPException(status_code=422, detail="Please agree to AI processing of your card image before scanning it.")
        # Decode each image locally to reject malformed or oversized pixel payloads before upload to the vision provider.
        prepared_images = [await run_in_threadpool(decode_and_prepare, item[2]) for item in data_by_side]
        result = await run_in_threadpool(_extract, [(image, "image/jpeg") for image in prepared_images])
        consent_at = datetime.now(timezone.utc).isoformat()
        tokens: dict[str, str] = {}
        for side, upload, data, mime_type in data_by_side:
            token = storage.stage(data, upload.filename or f"business-card-{side}", mime_type, {
                "ai_processing_consent_at": consent_at,
                "ai_processing_consent_notice_version": settings.consent_notice_version,
            })
            tokens[side] = token
            staged_tokens.append(token)
        result["business_card_tokens"] = tokens
        result["business_card_token"] = tokens["front"]
        return result
    except HTTPException:
        raise
    except InvalidImage as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except VisionConfigurationError:
        raise HTTPException(status_code=503, detail="Business-card scanning is not configured. You can enter your details manually.") from None
    except VisionUnavailable:
        for token in staged_tokens:
            storage.delete_staged(token)
        raise HTTPException(status_code=503, detail="Card scanning is temporarily unavailable. Your image was not saved; you can retry or enter your details manually.") from None
    except Exception:
        for token in staged_tokens:
            storage.delete_staged(token)
        logger.exception("Business-card extraction failed")
        raise HTTPException(
            status_code=503,
            detail="Card scanning is temporarily unavailable. You can retry or enter your details manually.",
        ) from None
    finally:
        for upload in uploads:
            await upload.close()
