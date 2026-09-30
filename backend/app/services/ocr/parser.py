import re
from collections.abc import Iterable

import phonenumbers
from phonenumbers import geocoder
from email_validator import EmailNotValidError, validate_email


ROLE_TERMS = (
    "chief executive", "chief technology", "chief operating", "chief financial", "ceo", "cto", "coo", "cfo", "cmo",
    "founder", "co-founder", "president", "vice president", "vp ", "director", "manager", "business development",
    "sales", "engineer", "architect", "consultant", "partner", "head of", "lead", "product", "innovation",
)
COMPANY_TERMS = ("technologies", "technology", "solutions", "labs", "software", "systems", "consult", "services", "limited", "pvt", "llc", "inc", "corporation", "group", "enterprises", "industries", "digital", "global")
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
WEB_RE = re.compile(r"(?:(?:https?://)?(?:www\.)?)(?:[A-Z0-9-]+\.)+(?:com|ai|io|co|in|org|net|tech|dev|uk|us|ca|au)(?:/[^\s]*)?", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+|00)?[\d(][\d\s()./-]{5,}\d(?!\w)")
COMPANY_SUFFIX = re.compile(r"\b(technologies|technology|solutions|labs|software|systems|consulting|consultants|services|private limited|pvt\.?\s*ltd\.?|ltd\.?|llc|inc\.?|corporation|group|enterprises|industries|global|digital)\b", re.I)
PERSONAL_EMAIL_DOMAINS = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "live.com", "msn.com", "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "mail.com", "yandex.com", "zoho.com"}


def _field(value: str | None, confidence: float = 0.0) -> dict[str, object]:
    return {"value": value or "", "confidence": round(max(0.0, min(confidence, 0.99)), 2)}


def _domain_label(address: str) -> str:
    domain = address.rsplit("@", 1)[-1].split(".", 1)[0]
    return re.sub(r"[-_]+", " ", domain).title()


def parse_card(blocks: Iterable[dict[str, object]], phone_region: str = "IN") -> dict[str, object]:
    source_blocks = list(blocks)
    rows = [str(block["text"]).strip() for block in source_blocks if str(block.get("text", "")).strip()]
    avg = sum(float(block.get("confidence", 0.5)) for block in source_blocks) / max(1, len(rows))
    text = "\n".join(rows)

    emails: list[str] = []
    for candidate in EMAIL_RE.findall(text):
        try:
            normalized = validate_email(candidate, check_deliverability=False).normalized
            if normalized.lower() not in [item.lower() for item in emails]:
                emails.append(normalized)
        except EmailNotValidError:
            continue
    # Prefer a company-domain address when a card lists both work and personal contacts.
    email = next((candidate for candidate in emails if candidate.rsplit("@", 1)[-1].lower() not in PERSONAL_EMAIL_DOMAINS), emails[0] if emails else "")

    phones: list[tuple[str, str, str, str]] = []
    for candidate in PHONE_RE.findall(text):
        try:
            parsed = phonenumbers.parse(candidate, phone_region)
            if phonenumbers.is_valid_number(parsed):
                formatted = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
                region = phonenumbers.region_code_for_number(parsed) or ""
                country_name = geocoder.country_name_for_number(parsed, "en") or region
                country_code = f"+{parsed.country_code}"
                if formatted not in [item[0] for item in phones]:
                    phones.append((formatted, region, country_name, country_code))
        except phonenumbers.NumberParseException:
            continue

    websites = WEB_RE.findall(EMAIL_RE.sub(" ", text))
    website = ""
    if websites:
        website = websites[0].rstrip(".,;)")
        if not website.lower().startswith(("http://", "https://")):
            website = f"https://{website}"

    role_index = next((i for i, row in enumerate(rows) if any(term in row.lower() for term in ROLE_TERMS)), -1)
    role = rows[role_index] if role_index >= 0 else ""
    company_index = next((i for i, row in enumerate(rows) if COMPANY_SUFFIX.search(row)), -1)
    if company_index < 0 and email:
        domain_name = _domain_label(email)
        company_index = next((i for i, row in enumerate(rows) if domain_name.lower() in row.lower()), -1)
    company = rows[company_index] if company_index >= 0 else ""

    excluded = set(emails + phones + websites)
    candidates = []
    for index, row in enumerate(rows):
        normalized = row.strip(" |,.;:-")
        if len(normalized.split()) not in (2, 3, 4) or normalized in excluded:
            continue
        if EMAIL_RE.search(normalized) or PHONE_RE.fullmatch(normalized) or WEB_RE.search(normalized):
            continue
        if ROLE_TERMS and any(term in normalized.lower() for term in ROLE_TERMS):
            continue
        if COMPANY_SUFFIX.search(normalized) or len(normalized) > 48 or re.search(r"\d{2,}", normalized):
            continue
        candidates.append((index, normalized))
    name = ""
    if candidates:
        ranked = sorted(candidates, key=lambda item: (2 if item[0] == 0 else 0) + min(len(item[1]), 24) / 24, reverse=True)
        name = ranked[0][1].title()
    elif company_index >= 0 and company_index > 0:
        name = rows[company_index - 1].title()

    email_type = "personal" if email and email.rsplit("@", 1)[-1].lower() in PERSONAL_EMAIL_DOMAINS else "work"
    email_type_confidence = 0.98 if email and email.rsplit("@", 1)[-1].lower() in PERSONAL_EMAIL_DOMAINS else (0.65 if email else 0)
    detected_phone = phones[0] if phones else ("", "", "", "")

    return {
        "full_name": _field(name, avg * (0.74 if name else 0)),
        "company": _field(company, avg * (0.84 if company else 0)),
        "job_title": _field(role, avg * (0.82 if role else 0)),
        "email": _field(email, 0.98 if email else 0),
        "email_type": _field(email_type if email else "work", email_type_confidence),
        "email_candidates": [{"value": candidate, "type": "personal" if candidate.rsplit("@", 1)[-1].lower() in PERSONAL_EMAIL_DOMAINS else "work"} for candidate in emails],
        "phone": _field(detected_phone[0], 0.94 if phones else 0),
        "phone_country": {"value": detected_phone[1], "name": detected_phone[2], "calling_code": detected_phone[3], "confidence": 0.94 if phones else 0},
        "website": _field(website, 0.93 if website else 0),
        "candidates": {"emails": emails, "phones": [item[0] for item in phones], "websites": websites},
        "ocr_text": text,
        "text_blocks": source_blocks,
    }
