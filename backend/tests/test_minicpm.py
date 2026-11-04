import unittest
from io import BytesIO

from PIL import Image

from app.services.vision.minicpm import parse_transcription, prepare_image


class MiniCPMParsingTests(unittest.TestCase):
    def test_exact_visible_fields_and_normalized_contact_values(self):
        result = parse_transcription(
            'Mira Sen\nQuality Engineer\nNorthstar Systems\nmira@northstar.example.com\n'
            '+1 415 555 2671\nwww.northstar.example.com'
        )
        self.assertEqual(result.full_name, 'Mira Sen')
        self.assertEqual(result.company, 'Northstar Systems')
        self.assertEqual(result.job_title, 'Quality Engineer')
        self.assertEqual(result.email, 'mira@northstar.example.com')
        self.assertEqual(result.phone, '+14155552671')
        self.assertEqual(result.website, 'https://www.northstar.example.com')
        self.assertIsNone(result.address)
        self.assertFalse(result.is_template)

    def test_absent_contacts_stay_empty(self):
        result = parse_transcription('Mira Sen\nQuality Engineer\nNorthstar Systems')
        self.assertEqual(result.full_name, 'Mira Sen')
        self.assertEqual(result.company, 'Northstar Systems')
        self.assertIsNone(result.email)
        self.assertIsNone(result.phone)
        self.assertIsNone(result.website)
        self.assertIsNone(result.address)

    def test_domain_does_not_create_company_or_name(self):
        result = parse_transcription('contact@northstar.example.com')
        self.assertIsNone(result.full_name)
        self.assertIsNone(result.company)
        self.assertIsNone(result.website)
        self.assertEqual(result.email, 'contact@northstar.example.com')

    def test_company_only_does_not_become_name(self):
        result = parse_transcription('Northstar Systems')
        self.assertIsNone(result.full_name)
        self.assertEqual(result.company, 'Northstar Systems')

    def test_ambiguous_names_and_numbers_are_left_for_review(self):
        result = parse_transcription('Mira Sen\nTara Rao\n+1 415 555 2671\n+1 415 555 2672')
        self.assertIsNone(result.full_name)
        self.assertIsNone(result.phone)
        self.assertIn('full_name', result.uncertain_fields)
        self.assertIn('phone', result.uncertain_fields)
        self.assertTrue(result.warnings)

    def test_template_markers_clear_demo_fields(self):
        result = parse_transcription('BUSINESS CARD TEMPLATE\nMira Sen\nNorthstar Systems\nmira@example.com')
        self.assertTrue(result.is_template)
        self.assertIsNone(result.full_name)
        self.assertIsNone(result.company)
        self.assertIsNone(result.email)
        self.assertTrue(result.warnings)

    def test_complete_email_address_is_not_standalone_placeholder(self):
        result = parse_transcription('Mira Sen\nNorthstar Systems\nmira@email.com')
        self.assertFalse(result.is_template)
        self.assertEqual(result.email, 'mira@email.com')
        for text in ['email.com', 'urname@email.com']:
            self.assertTrue(parse_transcription(text).is_template)

    def test_generic_example_word_is_not_template_marker(self):
        result = parse_transcription('Mira Sen\nExample Systems\nmira@example.com')
        self.assertFalse(result.is_template)
        self.assertEqual(result.full_name, 'Mira Sen')

    def test_name_case_is_preserved_and_address_requires_printed_evidence(self):
        result = parse_transcription('MIRA SEN\nNorthstar Systems\n42 Cedar Street\nBengaluru 560001')
        self.assertEqual(result.full_name, 'MIRA SEN')
        self.assertEqual(result.address, '42 Cedar Street')

    def test_company_first_and_mixed_case_name(self):
        result = parse_transcription('Northstar Systems\nMira de Silva\nQuality Engineer')
        self.assertEqual(result.full_name, 'Mira de Silva')
        self.assertEqual(result.company, 'Northstar Systems')

    def test_explicit_labels_and_mobile_preference(self):
        result = parse_transcription(
            'Name: Mira Sen\nCompany: Northstar\nTitle: Quality Engineer\n'
            'Office: +1 415 555 2671\nMobile: +1 415 555 2672\nAddress: 42 Cedar Street'
        )
        self.assertEqual(result.full_name, 'Mira Sen')
        self.assertEqual(result.company, 'Northstar')
        self.assertEqual(result.phone, '+14155552672')
        self.assertEqual(result.address, '42 Cedar Street')

    def test_name_only_does_not_invent_other_fields(self):
        result = parse_transcription('Mira Sen')
        self.assertEqual(result.full_name, 'Mira Sen')
        self.assertIsNone(result.company)
        self.assertIsNone(result.job_title)
        self.assertIsNone(result.email)
        self.assertIsNone(result.phone)
        self.assertIsNone(result.website)
        self.assertIsNone(result.address)
        self.assertTrue(result.warnings)

    def test_unsupported_and_overlong_model_text_is_rejected(self):
        for text in ['Mira\x00Sen', 'x' * 12001]:
            with self.assertRaises(ValueError):
                parse_transcription(text)

    def test_empty_transcription_is_not_a_success(self):
        with self.assertRaises(ValueError):
            parse_transcription('  ')


class MiniCPMImageTests(unittest.TestCase):
    def image(self, color, size=(1000, 620)):
        image = Image.new('RGB', size, color)
        output = BytesIO()
        image.save(output, format='PNG')
        return output.getvalue()

    def test_resize_keeps_original_bytes_untouched(self):
        source = self.image('red')
        encoded = prepare_image([(source, 'image/png')])
        with Image.open(BytesIO(encoded)) as image:
            self.assertEqual(image.size, (448, 278))
        with Image.open(BytesIO(source)) as original:
            self.assertEqual(original.size, (1000, 620))

    def test_both_sides_are_present_in_bounded_canvas(self):
        encoded = prepare_image([(self.image('red'), 'image/png'), (self.image('blue'), 'image/png')])
        with Image.open(BytesIO(encoded)) as image:
            self.assertEqual(image.size, (361, 448))
            self.assertEqual(image.getpixel((200, 50)), (255, 0, 0))
            self.assertEqual(image.getpixel((200, 400)), (0, 0, 255))


if __name__ == '__main__':
    unittest.main()
