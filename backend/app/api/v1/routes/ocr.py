import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.rate_limit import rate_limit
from app.services.ocr.engine import recognize
from app.services.ocr.parser import parse_card
from app.services.ocr.preprocess import InvalidImage, decode_and_prepare, detect_image_mime
from app.services.storage.business_cards import storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ocr", tags=["ocr"])
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _run_ocr_many(images: list[bytes]) -> dict[str, object]:
    blocks = []
    for data in images:
        blocks.extend(recognize(decode_and_prepare(data)))
    return parse_card(blocks, settings.default_phone_region)


@router.post("/business-card", dependencies=[Depends(rate_limit("ocr"))])
async def read_business_card(files: list[UploadFile] = File(default=[]), file: UploadFile | None = File(default=None)):
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
        # All recognition and preprocessing execute locally in the API process.
        # The upload is staged privately for the review/submit flow, not sent to an OCR vendor.
        result = await run_in_threadpool(_run_ocr_many, [item[2] for item in data_by_side])
        tokens: dict[str, str] = {}
        for side, upload, data, mime_type in data_by_side:
            token = storage.stage(data, upload.filename or f"business-card-{side}", mime_type)
            tokens[side] = token
            staged_tokens.append(token)
        result["business_card_tokens"] = tokens
        result["business_card_token"] = tokens["front"]
        return result
    except HTTPException:
        raise
    except InvalidImage as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception:
        for token in staged_tokens:
            storage.delete_staged(token)
        logger.exception("Local business-card OCR failed")
        raise HTTPException(
            status_code=503,
            detail="The local OCR engine or model is not ready. Install PaddleOCR and run the one-time local model warm-up before scanning cards.",
        ) from None
    finally:
        for upload in uploads:
            await upload.close()
