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
from app.services.vision.minicpm import parse_transcription, prepare_image
from app.services.vision.schemas import CardExtraction
from app.services.vision.vertex import build_request as build_vertex_request

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


def _request(images: list[tuple[bytes, str]], deadline: float | None = None) -> CardExtraction:
    deadline = deadline if deadline is not None else time.monotonic() + settings.ocr_timeout_seconds
    if not settings.ocr_enabled:
        raise VisionConfigurationError("Business-card scanning is disabled.")
    provider = settings.ocr_provider.lower()
    headers = {"Content-Type": "application/json"}
    if provider == "ollama":
        base = settings.ollama_base_url.rstrip("/")
        if not base.startswith(("http://", "https://")):
            raise VisionConfigurationError("Ollama base URL must use HTTP or HTTPS.")
        image = prepare_image(images)
        payload = {
            "model": settings.ollama_model,
            "messages": [{"role": "user", "content": "Text Recognition:",
                          "images": [base64.b64encode(image).decode("ascii")]}],
            "stream": False, "think": False, "keep_alive": "30m",
            "options": {"temperature": 0, "num_predict": settings.ocr_max_output_tokens,
                        "num_ctx": 8192, "num_thread": 2},
        }
        endpoint = f"{base}/api/chat"
        response_path = "ollama"
    elif provider == "openrouter":
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
        endpoint = f"{base}/chat/completions"
        headers.update({"Authorization": f"Bearer {settings.openrouter_api_key}", "HTTP-Referer": settings.frontend_url, "X-Title": "LatentSig Connect"})
        response_path = "openrouter"
    elif provider == "vertex":
        request = build_vertex_request(images, deadline)
        response_path = "vertex"
    else:
        raise VisionConfigurationError("Business-card scanning provider is not supported.")
    if provider != "vertex":
        request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        with urlopen(request, timeout=remaining) as response:
            body = json.loads(response.read())
        if time.monotonic() >= deadline:
            raise TimeoutError
        if response_path == "ollama":
            metrics = {key: body[key] for key in ("prompt_eval_count", "eval_count", "prompt_eval_duration", "eval_duration")
                       if isinstance(body.get(key), (int, float))}
            logger.info("OCR model completed: provider=ollama metrics=%s", metrics)
            if body.get("done") is not True or body.get("done_reason") != "stop":
                raise ValueError("OCR transcription was incomplete.")
            return parse_transcription(body["message"]["content"])
        if response_path == "vertex":
            candidate = body["candidates"][0]
            if candidate.get("finishReason") != "STOP":
                raise ValueError("OCR extraction was incomplete.")
            text = "".join(part.get("text", "") for part in candidate["content"]["parts"] if not part.get("thought"))
        else:
            if body["choices"][0].get("finish_reason") == "length":
                raise ValueError("OCR extraction was incomplete.")
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
        logger.warning("OCR provider request failed with HTTP status %s", exc.code)
        raise VisionUnavailable from None
    except TimeoutError:
        logger.warning("OCR provider request failed: provider=%s reason=timeout", provider)
        raise VisionUnavailable from None
    except (URLError, OSError, KeyError, IndexError, TypeError, ValueError, ValidationError):
        raise VisionUnavailable from None


def extract_card(images: list[tuple[bytes, str]]) -> CardExtraction:
    last_error = None
    started = time.monotonic()
    deadline = started + settings.ocr_timeout_seconds
    for attempt in range(settings.ocr_max_retries + 1):
        try:
            result = _request(images, deadline)
            logger.info("OCR provider request completed: provider=%s image_count=%s elapsed_seconds=%.2f reason=success",
                        settings.ocr_provider, len(images), time.monotonic() - started)
            return result
        except VisionConfigurationError:
            raise
        except VisionUnavailable as exc:
            last_error = exc
            if attempt < settings.ocr_max_retries:
                delay = min(0.25 * (2 ** attempt), 1.0)
                if time.monotonic() + delay >= deadline:
                    break
                time.sleep(delay)
    logger.warning("OCR provider request failed: provider=%s image_count=%s elapsed_seconds=%.2f reason=unavailable",
                   settings.ocr_provider, len(images), time.monotonic() - started)
    raise last_error or VisionUnavailable
