import argparse
from io import BytesIO
from getpass import getpass
from urllib.parse import urlsplit, urlunsplit

import phonenumbers

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from app.core.config import settings
from app.db.models import AuditLog, User
from app.db.session import SessionLocal
from app.core.passwords import hash_password
from app.services.vision.client import extract_card
from app.services.vision.exceptions import VisionConfigurationError, VisionUnavailable


def grant_admin(email: str) -> None:
    normalized_email = email.strip().lower()
    if normalized_email not in settings.admin_emails:
        raise SystemExit("Email is not present in ADMIN_EMAIL_ALLOWLIST.")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == normalized_email))
        if user is None:
            user = User(email=normalized_email, full_name=normalized_email.split("@", 1)[0].replace(".", " ").title(), role="ADMIN")
            db.add(user)
            db.flush()
        else:
            user.role = "ADMIN"
            user.is_active = True
        db.add(AuditLog(action="admin_role_granted", entity_type="user", entity_id=str(user.id), metadata_json={"email": normalized_email}))
        db.commit()
    print(f"ADMIN role granted to {normalized_email}.")


def set_password(email: str) -> None:
    normalized_email = email.strip().lower()
    if normalized_email not in settings.admin_emails:
        raise SystemExit("Email is not present in ADMIN_EMAIL_ALLOWLIST.")
    password = getpass("New password (minimum 12 characters): ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords did not match.")
    try:
        password_hash = hash_password(password)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == normalized_email))
        if user is None:
            user = User(
                email=normalized_email,
                full_name=normalized_email.split("@", 1)[0].replace(".", " ").title(),
                role="ADMIN" if normalized_email in settings.initial_admins else "SALES",
            )
            db.add(user)
        user.password_hash = password_hash
        user.is_active = True
        db.flush()
        db.add(AuditLog(action="team_password_set", entity_type="user", entity_id=str(user.id), metadata_json={"email": normalized_email}))
        db.commit()
    print(f"Password set for {normalized_email}.")


def verify_ocr() -> None:
    """Exercise configured provider/model using synthetic data; never print its response."""
    image = Image.new("RGB", (1000, 620), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=44)
    lines = ["Mira Sen", "Quality Engineer", "Northstar Systems", "mira@northstar.example.com",
             "+1 415 555 2671", "www.northstar.example.com"]
    for index, line in enumerate(lines):
        draw.text((45, 45 + index * 84), line, fill="black", font=font)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    try:
        result = extract_card([(buffer.getvalue(), "image/png")])
    except (VisionConfigurationError, VisionUnavailable):
        raise SystemExit("OCR smoke test failed. Check the configured provider and model availability.") from None
    expected = {
        "full_name": "Mira Sen", "company": "Northstar Systems", "job_title": "Quality Engineer",
        "email": "mira@northstar.example.com", "phone": "+14155552671",
        "website": "https://www.northstar.example.com", "address": None, "is_template": False,
    }
    actual = result.model_dump()
    if result.phone:
        try:
            phone = phonenumbers.parse(result.phone, settings.default_phone_region)
            actual["phone"] = phonenumbers.format_number(phone, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            pass
    if result.website:
        website = urlsplit(result.website if "://" in result.website else "https://" + result.website)
        actual["website"] = urlunsplit(("https", website.netloc.lower(), website.path.rstrip("/"), website.query, website.fragment))
    mismatches = [field for field, value in expected.items() if actual[field] != value]
    if mismatches:
        raise SystemExit("OCR smoke test failed field checks: " + ", ".join(mismatches))
    print("OCR smoke test passed. Synthetic image only; no lead was created and no extracted data was logged.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("grant-admin", help="Grant the ADMIN role to an allowlisted team account")
    admin.add_argument("email")
    password = commands.add_parser("set-password", help="Set an allowlisted team account password interactively")
    password.add_argument("email")
    commands.add_parser("verify-ocr", help="Verify card extraction with synthetic data")
    args = parser.parse_args()
    if args.command == "grant-admin":
        grant_admin(args.email)
    elif args.command == "set-password":
        set_password(args.email)
    elif args.command == "verify-ocr":
        verify_ocr()


if __name__ == "__main__":
    main()
