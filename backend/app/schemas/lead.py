from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

INTERESTS = {"AI Agents", "Data & Analytics", "Automation", "Software Development", "QA / Testing", "Product Development", "Partnership", "Other"}
INTENTS = {"I have a project", "I need a demo", "I am looking for a technology partner", "Partnership opportunity", "Investment / business discussion", "I want to explore LatentSig services", "Just connecting", "Other"}


def _strip_control_characters(value: str | None) -> str | None:
    if value is None:
        return None
    return "".join(character for character in value if character in "\n\t" or ord(character) >= 32 and ord(character) != 127)


class LeadSubmission(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    full_name: str = Field(min_length=2, max_length=180)
    company: str = Field(min_length=1, max_length=180)
    job_title: str = Field(min_length=1, max_length=180)
    email: EmailStr
    email_type: Literal["work", "personal"] = "work"
    phone: str = Field(min_length=7, max_length=40)
    website: str | None = Field(default=None, max_length=500)
    interest: list[str] = Field(min_length=1, max_length=8)
    intent: str = Field(min_length=1, max_length=180)
    other_interest_details: str | None = Field(default=None, max_length=100)
    other_intent_details: str | None = Field(default=None, max_length=100)
    requirement_message: str | None = Field(default=None, max_length=1000)
    capture_method: Literal["manual", "business_card"] = "manual"
    event_slug: str | None = Field(default=None, max_length=120)
    captured_by: str | None = Field(default=None, max_length=180)
    business_card_token: str | None = Field(default=None, max_length=36)
    business_card_back_token: str | None = Field(default=None, max_length=36)
    business_card_ocr: dict | None = None
    source: str = Field(default="direct", max_length=180)
    utm_source: str | None = Field(default=None, max_length=180)
    utm_medium: str | None = Field(default=None, max_length=180)
    utm_campaign: str | None = Field(default=None, max_length=180)

    @field_validator("website")
    @classmethod
    def normalize_website(cls, value: str | None) -> str | None:
        if value and not value.startswith(("https://", "http://")):
            return f"https://{value}"
        return value

    @field_validator("full_name", "company", "job_title", "other_interest_details", "other_intent_details", "requirement_message", "source", "captured_by", "utm_source", "utm_medium", "utm_campaign")
    @classmethod
    def remove_control_characters(cls, value: str | None) -> str | None:
        return _strip_control_characters(value)

    @field_validator("interest")
    @classmethod
    def validate_interests(cls, value: list[str]) -> list[str]:
        if any(item not in INTERESTS for item in value):
            raise ValueError("Choose only the listed interest options.")
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def require_other_interest_details(self):
        required_answers = []
        if "Other" in self.interest:
            required_answers.append((self.other_interest_details, "Please explain your interest in 5 words or fewer."))
        if self.intent == "Other":
            required_answers.append((self.other_intent_details, "Please explain what you would like to discuss in 5 words or fewer."))
        for answer, error in required_answers:
            detail = (answer or "").strip()
            if not detail:
                raise ValueError(error)
            if len(detail.split()) > 5:
                raise ValueError("Keep your explanation to 5 words or fewer.")
        return self

    @field_validator("intent")
    @classmethod
    def validate_intent(cls, value: str) -> str:
        if value not in INTENTS:
            raise ValueError("Choose one of the listed discussion options.")
        return value
