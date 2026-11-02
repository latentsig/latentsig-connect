import argparse
from io import BytesIO
from getpass import getpass

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
    image = Image.new("RGB", (1000, 520), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((24, 24, 976, 496), outline="#183153", width=5)
    font = ImageFont.load_default(size=38)
    draw.text((65, 80), "LATENTSIG  |  SYNTHETIC TEST CARD", fill="#183153", font=font)
    draw.text((65, 180), "Alex Example", fill="#101820", font=font)
    draw.text((65, 245), "Quality Engineer", fill="#101820", font=font)
    draw.text((65, 310), "Example Test Company", fill="#101820", font=font)
    draw.text((65, 375), "ocr-smoke@example.invalid", fill="#101820", font=font)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    try:
        result = extract_card([(buffer.getvalue(), "image/png")])
    except (VisionConfigurationError, VisionUnavailable):
        raise SystemExit("OpenRouter OCR smoke test failed. Check the production provider configuration and model availability.") from None
    if result.is_template:
        raise SystemExit("OpenRouter OCR smoke test returned an unexpected template classification.")
    print("OpenRouter OCR smoke test passed. Synthetic image only; no lead was created and no extracted data was logged.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("grant-admin", help="Grant the ADMIN role to an allowlisted team account")
    admin.add_argument("email")
    password = commands.add_parser("set-password", help="Set an allowlisted team account password interactively")
    password.add_argument("email")
    commands.add_parser("verify-ocr", help="Verify OpenRouter card extraction with synthetic data")
    args = parser.parse_args()
    if args.command == "grant-admin":
        grant_admin(args.email)
    elif args.command == "set-password":
        set_password(args.email)
    elif args.command == "verify-ocr":
        verify_ocr()


if __name__ == "__main__":
    main()
