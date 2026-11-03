import unittest
from unittest.mock import patch

from app.cli import verify_ocr
from app.services.vision.schemas import CardExtraction


class OCRVerificationTests(unittest.TestCase):
    def result(self, **changes):
        fields = dict(full_name='Mira Sen', company='Northstar Systems', job_title='Quality Engineer',
                      email='mira@northstar.example.com', phone='+14155552671',
                      website='https://www.northstar.example.com')
        fields.update(changes)
        return CardExtraction(**fields)

    def test_exact_extraction_passes(self):
        with patch('app.cli.extract_card', return_value=self.result()), patch('builtins.print') as output:
            verify_ocr()
        self.assertIn('passed', output.call_args.args[0])

    def test_hosted_printed_phone_and_website_pass_without_changing_result(self):
        result = self.result(phone='+1 415 555 2671', website='www.northstar.example.com')
        with patch('app.cli.extract_card', return_value=result), patch('builtins.print'):
            verify_ocr()
        self.assertEqual(result.phone, '+1 415 555 2671')
        self.assertEqual(result.website, 'www.northstar.example.com')

    def test_blank_wrong_and_template_results_fail_literal_checks(self):
        results = [CardExtraction(), self.result(email=None), self.result(phone='+14155552672'),
                   self.result(is_template=True), self.result(address='Invented address')]
        for result in results:
            with self.subTest(result=result), patch('app.cli.extract_card', return_value=result):
                with self.assertRaisesRegex(SystemExit, 'failed field checks'):
                    verify_ocr()
