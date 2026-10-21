import base64
import json
import logging
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import ValidationError

from app.core.config import settings
from app.services.vision.exceptions import VisionConfigurationError, VisionUnavailable
from app.services.vision.prompts import SYSTEM_PROMPT
from app.services.vision.schemas import CardExtraction

logger = logging.getLogger(__name__)

_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "full_name": {"type": ["string", "null"]}, "company": {"type": ["string", "null"]},
        "job_title": {"type": ["string", "null"]}, "email": {"type": ["string", "null"]},
        "phone": {"type": ["string", "null"]}, "website": {"type": ["string", "null"]},
        "address": {"type": ["string", "null"]},
        "is_template": {"type": "boolean"},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "uncertain_fields": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["full_name", "company", "job_title", "email", "phone", "website", "address", "is_template", "warnings", "uncertain_fields"],
    "additionalProperties": False,
}


def _request(images: list[tuple[bytes, str]]) -> CardExtraction:
    if not settings.ocr_enabled:
        raise VisionConfigurationError("Business-card scanning is disabled.")
    if not settings.openrouter_api_key:
        raise VisionConfigurationError("Business-card scanning is not configured.")
    base = settings.openrouter_base_url.rstrip("/")
    if not base.startswith("https://"):
        raise VisionConfigurationError("OpenRouter base URL must use HTTPS.")
    content: list[dict[str, object]] = [{"type": "text", "text": "Extract contact details from these card image(s)."}]
    for image, mime_type in images:
        encoded = base64.b64encode(image).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}})
    payload = {
        "model": settings.openrouter_model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}],
        "max_tokens": settings.ocr_max_output_tokens,
        "temperature": 0,
        "response_format": {"type": "json_schema", "json_schema": {"name": "business_card", "strict": True, "schema": _JSON_SCHEMA}},
    }
    request = Request(f"{base}/chat/completions", data=json.dumps(payload).encode("utf-8"), headers={
        "Authorization": f"Bearer {settings.openrouter_api_key}", "Content-Type": "application/json",
        "HTTP-Referer": settings.frontend_url, "X-Title": "LatentSig Connect",
    }, method="POST")
    try:
        with urlopen(request, timeout=settings.ocr_timeout_seconds) as response:
            body = json.loads(response.read())
        text = body["choices"][0]["message"]["content"]
        if isinstance(text, list):
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        parsed = CardExtraction.model_validate_json(text)
        # Treat blank strings as missing rather than propagating phantom values.
        cleaned = {key: (None if isinstance(value, str) and not value.strip() else value)
            for key, value in parsed.model_dump().items()}
        if cleaned["is_template"]:
            for field in ("full_name", "company", "job_title", "email", "phone", "website", "address"):
                cleaned[field] = None
            template_warning = "This image looks like a card template or mockup. Upload a photo of your completed business card to extract real contact details."
            if not any("template" in warning.lower() or "mockup" in warning.lower() for warning in cleaned["warnings"]):
                cleaned["warnings"].append(template_warning)
        return CardExtraction.model_validate(cleaned)
    except HTTPError as exc:
        # Do not log provider response bodies: they may contain submitted data.
        logger.warning("OpenRouter request failed with HTTP status %s", exc.code)
        raise VisionUnavailable from None
    except (URLError, TimeoutError, OSError, KeyError, IndexError, TypeError, ValueError, ValidationError):
        raise VisionUnavailable from None


def extract_card(images: list[tuple[bytes, str]]) -> CardExtraction:
    last_error = None
    for attempt in range(settings.ocr_max_retries + 1):
        try:
            return _request(images)
        except VisionConfigurationError:
            raise
        except VisionUnavailable as exc:
            last_error = exc
            if attempt < settings.ocr_max_retries:
                time.sleep(min(0.25 * (2 ** attempt), 1.0))
    raise last_error or VisionUnavailable
