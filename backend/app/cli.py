import argparse
from getpass import getpass

from sqlalchemy import select

from app.core.config import settings
from app.db.models import AuditLog, User
from app.db.session import SessionLocal
from app.core.passwords import hash_password


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


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("grant-admin", help="Grant the ADMIN role to an allowlisted team account")
    admin.add_argument("email")
    password = commands.add_parser("set-password", help="Set an allowlisted team account password interactively")
    password.add_argument("email")
    args = parser.parse_args()
    if args.command == "grant-admin":
        grant_admin(args.email)
    elif args.command == "set-password":
        set_password(args.email)


if __name__ == "__main__":
    main()
