import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.api.v1.routes.ocr import router
from app.core import rate_limit
from app.core.config import settings
from app.services.storage.business_cards import BusinessCardStorage
from app.services.vision.exceptions import VisionUnavailable


class OCRProviderAPITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.options = patch.multiple(settings, ocr_provider='ollama', ocr_max_retries=0, redis_url='',
                                      private_storage_dir=Path(self.directory.name), storage_provider='local', app_env='development')
        self.options.start()
        self.addCleanup(self.options.stop)
        self.storage = BusinessCardStorage()
        storage_patch = patch('app.api.v1.routes.ocr.storage', self.storage)
        storage_patch.start()
        self.addCleanup(storage_patch.stop)
        rate_limit._hits.clear()
        app = FastAPI()
        app.include_router(router, prefix='/api/v1')
        self.client = TestClient(app)

    def image(self, color='white'):
        output = BytesIO()
        Image.new('RGB', (1000, 620), color).save(output, format='PNG')
        return output.getvalue()

    def response(self, text):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self): return json.dumps({'done': True, 'done_reason': 'stop', 'message': {'content': text}}).encode()
        return Response()

    def scan(self, text, images):
        with patch('app.services.vision.client.urlopen', return_value=self.response(text)) as provider:
            response = self.client.post('/api/v1/ocr/business-card',
                                        files=[('files', ('synthetic.png', image, 'image/png')) for image in images],
                                        data={'ai_processing_consent': 'true'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(provider.call_count, 1)
        return response.json()

    def test_two_sides_preserve_originals_and_exact_visible_values(self):
        front, back = self.image('red'), self.image('blue')
        result = self.scan('Mira Sen\nQuality Engineer\nNorthstar Systems\nmira@northstar.example.com\n'
                           '+1 415 555 2671\nwww.northstar.example.com', [front, back])
        expected = {'full_name': 'Mira Sen', 'company': 'Northstar Systems', 'job_title': 'Quality Engineer',
                    'email': 'mira@northstar.example.com', 'phone': '+14155552671',
                    'website': 'https://www.northstar.example.com', 'address': ''}
        for field, value in expected.items():
            self.assertEqual(result[field]['value'], value)
        self.assertEqual(set(result['business_card_tokens']), {'front', 'back'})
        for side, original in [('front', front), ('back', back)]:
            self.assertEqual(self.storage.staging_path(result['business_card_tokens'][side]).read_bytes(), original)

    def test_absent_fields_stay_empty_in_review_response(self):
        result = self.scan('Mira Sen\nQuality Engineer\nNorthstar Systems', [self.image()])
        self.assertFalse(result['is_template'])
        self.assertEqual(result['full_name']['value'], 'Mira Sen')
        for field in ['email', 'phone', 'website', 'address']:
            self.assertEqual(result[field]['value'], '')
        self.assertTrue(result['warnings'])

    def test_template_is_rejected_and_empty_ocr_preserves_image_for_manual_review(self):
        result = self.scan('BUSINESS CARD TEMPLATE\nYour Name\nCompany Logo', [self.image()])
        self.assertTrue(result['is_template'])
        self.assertEqual(result['full_name']['value'], '')
        with patch('app.api.v1.routes.ocr.extract_card', side_effect=VisionUnavailable):
            response = self.client.post('/api/v1/ocr/business-card', files={'files': ('synthetic.png', self.image(), 'image/png')},
                                        data={'ai_processing_consent': 'true'})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['ocr_status'], 'unavailable')
        token = result['business_card_tokens']['front']
        self.assertEqual(self.storage.staging_path(token).read_bytes(), self.image())
        self.storage.delete_staged(token)
