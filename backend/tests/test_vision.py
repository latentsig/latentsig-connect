import json
import unittest
from unittest.mock import patch

from app.core.config import settings
from app.services.vision.client import _request


class VisionClientTests(unittest.TestCase):
    def setUp(self):
        self.original = {name: getattr(settings, name) for name in (
            "openrouter_api_key", "openrouter_base_url", "openrouter_model", "ocr_enabled",
            "ocr_timeout_seconds", "ocr_max_output_tokens", "ocr_context_tokens", "ocr_provider", "ollama_base_url", "ollama_model",
        )}
        settings.openrouter_api_key = "test-key"
        settings.openrouter_base_url = "https://openrouter.ai/api/v1"
        settings.openrouter_model = "google/gemini-3.8-flash"
        settings.ocr_enabled = True

    def tearDown(self):
        for name, value in self.original.items():
            setattr(settings, name, value)

    def test_sends_images_to_configured_model_and_validates_json(self):
        result_body = {"choices": [{"message": {"content": json.dumps({
            "full_name": "Ananya Rao", "company": "Example Labs", "job_title": "Founder",
            "email": "ananya@example.com", "phone": "+919876543210", "website": None,
            "address": None, "is_template": False, "warnings": [], "uncertain_fields": [],
        })}}]}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps(result_body).encode()

        with patch("app.services.vision.client.urlopen", return_value=Response()) as open_url:
            result = _request([(b"normalized-image", "image/jpeg")])
        self.assertEqual(result.full_name, "Ananya Rao")
        self.assertIsNone(result.website)
        request = open_url.call_args.args[0]
        sent = json.loads(request.data)
        self.assertEqual(sent["model"], settings.openrouter_model)
        self.assertEqual(sent["messages"][1]["content"][1]["type"], "image_url")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")

    def test_returns_null_fields_for_missing_values(self):
        body = {"choices": [{"message": {"content": json.dumps({
            "full_name": None, "company": None, "job_title": None, "email": None,
            "phone": None, "website": None, "address": None, "is_template": False, "warnings": [], "uncertain_fields": [],
        })}}]}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self): return json.dumps(body).encode()

        with patch("app.services.vision.client.urlopen", return_value=Response()):
            result = _request([(b"normalized-image", "image/jpeg")])
        self.assertIsNone(result.full_name)
        self.assertIsNone(result.phone)

    def test_template_images_are_not_returned_as_real_contact_details(self):
        result_body = {"choices": [{"message": {"content": json.dumps({
            "full_name": "MICHAL JOHNS", "company": None, "job_title": "Solution Manager",
            "email": "urname@email.com", "phone": None, "website": "www.websitename.com",
            "address": "Street Address Here Singapore, 2222", "is_template": True,
            "warnings": [], "uncertain_fields": [],
        })}}]}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self): return json.dumps(result_body).encode()

        with patch("app.services.vision.client.urlopen", return_value=Response()):
            result = _request([(b"normalized-image", "image/jpeg")])
        self.assertTrue(result.is_template)
        self.assertIsNone(result.full_name)
        self.assertIsNone(result.email)
        self.assertIsNone(result.website)
        self.assertIsNone(result.address)
        self.assertTrue(result.warnings)
        self.assertEqual(len(result.warnings), 1)

    def test_gcp_ollama_uses_mounted_minicpm_model_and_structured_image_input(self):
        result_body = {"message": {"content": json.dumps({
            "full_name": "Alex Example", "company": "Example Company", "job_title": "Engineer",
            "email": "alex@example.invalid", "phone": None, "website": None, "address": None,
            "is_template": False, "warnings": [], "uncertain_fields": [],
        })}}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self): return json.dumps(result_body).encode()

        settings.ocr_provider = "ollama"
        settings.ollama_base_url = "http://ollama:11434"
        settings.ollama_model = "openbmb/minicpm-ocr1.0"
        with patch("app.services.vision.client.urlopen", return_value=Response()) as open_url:
            result = _request([(b"synthetic-image", "image/jpeg")])
        request = open_url.call_args.args[0]
        sent = json.loads(request.data)
        self.assertEqual(request.full_url, "http://ollama:11434/api/chat")
        self.assertEqual(sent["model"], "openbmb/minicpm-ocr1.0")
        self.assertEqual(sent["messages"][1]["images"], ["c3ludGhldGljLWltYWdl"])
        self.assertEqual(sent["format"]["type"], "object")
        self.assertEqual(sent["options"]["num_ctx"], 8192)
        self.assertIn("JSON object", sent["messages"][1]["content"])
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(result.full_name, "Alex Example")


if __name__ == "__main__":
    unittest.main()
