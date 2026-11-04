import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from google.auth.exceptions import DefaultCredentialsError

from app.core.config import Settings, settings
from app.services.vision.client import extract_card
from app.services.vision.exceptions import VisionUnavailable


class VertexVisionTests(unittest.TestCase):
    def setUp(self):
        self.original = {name: getattr(settings, name) for name in (
            "ocr_provider", "ocr_enabled", "ocr_max_retries", "google_cloud_project", "vertex_ai_model",
        )}
        self.addCleanup(lambda: [setattr(settings, name, value) for name, value in self.original.items()])
        settings.ocr_provider = "vertex"
        settings.ocr_enabled = True
        settings.ocr_max_retries = 0
        settings.google_cloud_project = "test-project-123"
        settings.vertex_ai_model = "gemini-3.5-flash-lite"
        self.credentials = Mock()
        self.credentials.before_request.side_effect = lambda request, method, url, headers: headers.update({"authorization": "Bearer synthetic-token"})
        auth_patch = patch("app.services.vision.vertex.google.auth.default", return_value=(self.credentials, None))
        self.auth = auth_patch.start()
        self.addCleanup(auth_patch.stop)

    def response(self, content=None, reason="STOP"):
        fields = {"full_name": "Mira Sen", "company": None, "job_title": None,
                  "email": "mira@example.com", "phone": None, "website": None, "address": None,
                  "is_template": False, "warnings": [], "uncertain_fields": []}
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({"candidates": [{
            "finishReason": reason, "content": {"parts": [{"text": "private reasoning", "thought": True},
                                                         {"text": json.dumps(content or fields)}]},
        }]}).encode()
        return response

    def test_vertex_sends_both_images_and_parses_structured_fields(self):
        with patch("app.services.vision.client.urlopen", return_value=self.response()) as open_url:
            result = extract_card([(b"front", "image/jpeg"), (b"back", "image/png")])
        self.assertEqual(result.full_name, "Mira Sen")
        self.assertEqual(result.email, "mira@example.com")
        self.assertIsNone(result.address)
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, "https://aiplatform.googleapis.com/v1/projects/test-project-123/locations/global/publishers/google/models/gemini-3.5-flash-lite:generateContent")
        self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-token")
        payload = json.loads(request.data)
        self.assertEqual(payload["contents"][0]["parts"][1:], [
            {"inlineData": {"mimeType": "image/jpeg", "data": "ZnJvbnQ="}},
            {"inlineData": {"mimeType": "image/png", "data": "YmFjaw=="}},
        ])
        self.assertEqual(payload["generationConfig"]["thinkingConfig"], {"thinkingLevel": "LOW"})
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(self.auth.call_args.kwargs["scopes"], ["https://www.googleapis.com/auth/cloud-platform"])
        self.assertGreater(open_url.call_args.kwargs["timeout"], 0)

    def test_auth_failure_does_not_send_image_or_fall_back(self):
        self.auth.side_effect = DefaultCredentialsError("sensitive credential detail")
        with patch("app.services.vision.client.urlopen") as open_url, \
                self.assertLogs("app.services.vision.client", level="WARNING") as logs:
            with self.assertRaises(VisionUnavailable):
                extract_card([(b"private-image", "image/png")])
        open_url.assert_not_called()
        self.assertNotIn("sensitive credential detail", " ".join(logs.output))
        self.assertEqual(settings.ocr_provider, "vertex")

    def test_http_failure_does_not_fall_back(self):
        failure = HTTPError("https://aiplatform.googleapis.com", 403, "forbidden", {}, None)
        with patch("app.services.vision.client.urlopen", side_effect=failure) as open_url:
            with self.assertRaises(VisionUnavailable):
                extract_card([(b"front", "image/png")])
        self.assertEqual(open_url.call_count, 1)
        self.assertIn("aiplatform.googleapis.com", open_url.call_args.args[0].full_url)

    def test_truncated_or_blocked_result_is_rejected(self):
        for reason in ("MAX_TOKENS", "SAFETY", None):
            with self.subTest(reason=reason), patch("app.services.vision.client.urlopen", return_value=self.response(reason=reason)):
                with self.assertRaises(VisionUnavailable):
                    extract_card([(b"front", "image/png")])

    def test_vertex_keeps_template_guard(self):
        fields = {"full_name": "Demo Name", "email": "demo@example.com", "is_template": True,
                  "warnings": [], "uncertain_fields": []}
        with patch("app.services.vision.client.urlopen", return_value=self.response(content=fields)):
            result = extract_card([(b"front", "image/png")])
        self.assertTrue(result.is_template)
        self.assertIsNone(result.full_name)
        self.assertIsNone(result.email)
        self.assertTrue(result.warnings)


class VertexConfigurationTests(unittest.TestCase):
    def test_vertex_requires_valid_explicit_project_and_model(self):
        for values in ({}, {"google_cloud_project": "../unsafe"},
                       {"google_cloud_project": "test-project", "vertex_ai_model": "../../unsafe"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                Settings(_env_file=None, ocr_provider="vertex", **values)

    def test_project_alias_and_lite_default(self):
        configured = Settings(_env_file=None, ocr_provider="vertex", GCP_PROJECT_ID="test-project")
        self.assertEqual(configured.google_cloud_project, "test-project")
        self.assertEqual(configured.vertex_ai_model, "gemini-3.5-flash-lite")
