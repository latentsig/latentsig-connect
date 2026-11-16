from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.db.models import AuditLog, BusinessCard, StaffCardCapture
from app.db.session import SessionLocal
from app.services.storage.business_cards import storage


def purge_expired_cards() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, settings.business_card_retention_days))
    with SessionLocal() as db:
        cards = db.scalars(select(BusinessCard).where(BusinessCard.created_at < cutoff)).all()
        captures = db.scalars(select(StaffCardCapture).where(StaffCardCapture.created_at < cutoff)).all()
        paths = {card.storage_path for card in cards}
        paths.update(card.back_storage_path for card in cards if card.back_storage_path)
        paths.update(capture.storage_path for capture in captures)
        for path in paths:
            storage.delete(path)
        for card in cards:
            db.add(AuditLog(
                action="business_card_retention_purged", entity_type="business_card",
                entity_id=str(card.id), metadata_json={"lead_id": str(card.lead_id), "retention_days": settings.business_card_retention_days},
            ))
            db.delete(card)
        for capture in captures:
            db.add(AuditLog(
                action="staff_card_retention_purged", entity_type="staff_card_capture",
                entity_id=str(capture.id), metadata_json={"event_id": str(capture.event_id) if capture.event_id else None, "retention_days": settings.business_card_retention_days},
            ))
            db.delete(capture)
        db.commit()
        return len(paths)


def main() -> None:
    count = purge_expired_cards()
    print(f"Purged {count} business-card image(s) past the {settings.business_card_retention_days}-day retention period.")


if __name__ == "__main__":
    main()
