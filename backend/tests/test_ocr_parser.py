import unittest

from app.schemas.lead import LeadSubmission
from app.services.ocr.parser import parse_card


class CardParserTests(unittest.TestCase):
    def test_extracts_contact_fields_and_prefers_work_email(self):
        text = [
            "Rachel Thomas", "VP Innovation", "ABC Technologies",
            "rachel@gmail.com", "rachel@abctech.com", "+1 415 555 2671", "www.abctech.com",
        ]
        result = parse_card([{"text": item, "confidence": 0.95} for item in text])
        self.assertEqual(result["full_name"]["value"], "Rachel Thomas")
        self.assertEqual(result["company"]["value"], "ABC Technologies")
        self.assertEqual(result["job_title"]["value"], "VP Innovation")
        self.assertEqual(result["email"]["value"], "rachel@abctech.com")
        self.assertEqual(result["email_type"]["value"], "work")
        self.assertEqual(result["phone"]["value"], "+14155552671")
        self.assertEqual(result["phone_country"]["value"], "US")
        self.assertEqual(result["website"]["value"], "https://www.abctech.com")
        self.assertEqual([item["type"] for item in result["email_candidates"]], ["personal", "work"])


class LeadSchemaTests(unittest.TestCase):
    def test_website_normalization_and_interest_deduplication(self):
        payload = LeadSubmission(
            full_name="Taylor Example", company="Example Co", job_title="CTO",
            email="taylor@example.com", phone="+14155552671", website="example.com",
            interest=["AI Agents", "AI Agents"], intent="I need a demo", data_processing_consent=True,
        )
        self.assertEqual(payload.website, "https://example.com")
        self.assertEqual(payload.interest, ["AI Agents"])

    def test_rejects_unlisted_interest(self):
        with self.assertRaises(ValueError):
            LeadSubmission(
                full_name="Taylor Example", company="Example Co", job_title="CTO",
                email="taylor@example.com", phone="+14155552671", interest=["Unlisted"],
                intent="I need a demo", data_processing_consent=True,
            )


if __name__ == "__main__":
    unittest.main()
