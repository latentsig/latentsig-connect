import argparse

from sqlalchemy import select

from app.core.config import settings
from app.db.models import AuditLog, User
from app.db.session import SessionLocal


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


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("grant-admin", help="Grant the ADMIN role to an allowlisted team account")
    admin.add_argument("email")
    args = parser.parse_args()
    if args.command == "grant-admin":
        grant_admin(args.email)


if __name__ == "__main__":
    main()
