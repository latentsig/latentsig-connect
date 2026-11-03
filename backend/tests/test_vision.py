import json
from io import BytesIO

from PIL import Image
import unittest
from unittest.mock import patch

from app.core.config import settings
from app.services.vision.client import _request, extract_card
from app.services.vision.exceptions import VisionUnavailable


class VisionClientTests(unittest.TestCase):
    def setUp(self):
        self.original = {name: getattr(settings, name) for name in (
            "openrouter_api_key", "openrouter_base_url", "openrouter_model", "ocr_enabled",
            "ocr_timeout_seconds", "ocr_max_retries", "ocr_max_output_tokens", "ocr_provider", "ollama_base_url", "ollama_model",
        )}
        settings.openrouter_api_key = "test-key"
        settings.openrouter_base_url = "https://openrouter.ai/api/v1"
        settings.openrouter_model = "google/gemini-3.8-flash"
        settings.ocr_enabled = True
        settings.ocr_provider = "openrouter"

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

    def image(self):
        output = BytesIO()
        Image.new("RGB", (1000, 620), "white").save(output, format="PNG")
        return output.getvalue()

    def response(self, body):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self): return json.dumps(body).encode()
        return Response()

    def test_ollama_uses_official_transcription_task_and_bounded_image(self):
        settings.ocr_provider = "ollama"
        settings.ollama_base_url = "http://ollama:11434"
        body = {"done": True, "done_reason": "stop", "message": {"content": "Mira Sen\nQuality Engineer\nNorthstar Systems"}}
        with patch("app.services.vision.client.urlopen", return_value=self.response(body)) as open_url:
            result = _request([(self.image(), "image/png")])
        request = open_url.call_args.args[0]
        sent = json.loads(request.data)
        self.assertEqual(request.full_url, "http://ollama:11434/api/chat")
        self.assertEqual(sent["model"], "openbmb/minicpm-ocr1.0")
        self.assertEqual(sent["messages"][0]["content"], "Text Recognition:")
        self.assertEqual(len(sent["messages"]), 1)
        self.assertEqual(len(sent["messages"][0]["images"]), 1)
        self.assertNotIn("format", sent)
        self.assertEqual(sent["options"]["num_ctx"], 8192)
        self.assertEqual(sent["options"]["num_thread"], 2)
        self.assertEqual(sent["keep_alive"], "30m")
        self.assertFalse(sent["think"])
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(result.full_name, "Mira Sen")
        self.assertIsNone(result.phone)

    def test_two_sides_use_one_call_and_both_sides_are_parsed(self):
        settings.ocr_provider = "ollama"
        body = {"done": True, "done_reason": "stop", "message": {"content": "Mira Sen\nNorthstar Systems\nmira@northstar.example.com"}}
        with patch("app.services.vision.client.urlopen", return_value=self.response(body)) as open_url:
            result = extract_card([(self.image(), "image/png"), (self.image(), "image/png")])
        self.assertEqual(open_url.call_count, 1)
        self.assertEqual(result.full_name, "Mira Sen")
        self.assertEqual(result.email, "mira@northstar.example.com")

    def test_truncated_transcription_is_not_accepted(self):
        settings.ocr_provider = "ollama"
        body = {"done": True, "done_reason": "length", "message": {"content": "Mira Sen"}}
        with patch("app.services.vision.client.urlopen", return_value=self.response(body)):
            with self.assertRaises(VisionUnavailable):
                _request([(self.image(), "image/png")])

    def test_deadline_includes_preparation_and_all_retries(self):
        settings.ocr_max_retries = 2
        settings.ocr_timeout_seconds = 1
        with patch("app.services.vision.client.time.monotonic", side_effect=[0, 0.9, 1.0]), \
                patch("app.services.vision.client._request", side_effect=VisionUnavailable) as request, \
                patch("app.services.vision.client.time.sleep") as sleep:
            with self.assertRaises(VisionUnavailable):
                extract_card([(self.image(), "image/png")])
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[1], 1)
        sleep.assert_not_called()

    def test_preparation_cannot_start_provider_call_after_deadline(self):
        settings.ocr_provider = "ollama"
        with patch("app.services.vision.client.time.monotonic", return_value=11), \
                patch("app.services.vision.client.urlopen") as open_url:
            with self.assertRaises(VisionUnavailable):
                _request([(self.image(), "image/png")], deadline=10)
        open_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()
