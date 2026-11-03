import base64
import json
import time
from urllib.request import Request

import google.auth
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as AuthRequest
import requests

from app.core.config import settings
from app.services.vision.exceptions import VisionUnavailable
from app.services.vision.prompts import SYSTEM_PROMPT

_CONTACT_FIELDS = ("full_name", "company", "job_title", "email", "phone", "website", "address")


def build_request(images: list[tuple[bytes, str]], deadline: float) -> Request:
    properties = {field: {"type": "STRING", "nullable": True} for field in _CONTACT_FIELDS}
    properties.update({
        "is_template": {"type": "BOOLEAN"},
        "warnings": {"type": "ARRAY", "items": {"type": "STRING"}},
        "uncertain_fields": {"type": "ARRAY", "items": {"type": "STRING"}},
    })
    parts = [{"text": "Extract contact details from these business card images."}]
    parts.extend({"inlineData": {"mimeType": mime_type, "data": base64.b64encode(image).decode("ascii")}}
                 for image, mime_type in images)
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "maxOutputTokens": settings.ocr_max_output_tokens,
            "thinkingConfig": {"thinkingLevel": "LOW"},
            "responseMimeType": "application/json",
            "responseSchema": {"type": "OBJECT", "properties": properties, "required": list(properties)},
        },
    }
    endpoint = ("https://aiplatform.googleapis.com/v1/projects/" + settings.google_cloud_project
                + "/locations/global/publishers/google/models/" + settings.vertex_ai_model + ":generateContent")
    headers = {"Content-Type": "application/json", "x-goog-user-project": settings.google_cloud_project}
    try:
        with requests.Session() as session:
            transport = AuthRequest(session=session)

            def auth_request(*args, **kwargs):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                kwargs["timeout"] = min(kwargs.get("timeout") or remaining, remaining)
                return transport(*args, **kwargs)

            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"], request=auth_request)
            credentials.before_request(auth_request, "POST", endpoint, headers)
    except (GoogleAuthError, requests.RequestException, OSError):
        raise VisionUnavailable from None
    return Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
