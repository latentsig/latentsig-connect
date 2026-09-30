from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.db.models import AuditLog, BusinessCard
from app.db.session import SessionLocal
from app.services.storage.business_cards import storage


def purge_expired_cards() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, settings.business_card_retention_days))
    with SessionLocal() as db:
        cards = db.scalars(select(BusinessCard).where(BusinessCard.created_at < cutoff)).all()
        for card in cards:
            storage.delete(card.storage_path)
            if card.back_storage_path:
                storage.delete(card.back_storage_path)
            db.add(AuditLog(
                action="business_card_retention_purged", entity_type="business_card",
                entity_id=str(card.id), metadata_json={"lead_id": str(card.lead_id), "retention_days": settings.business_card_retention_days},
            ))
            db.delete(card)
        db.commit()
        return len(cards)


def main() -> None:
    count = purge_expired_cards()
    print(f"Purged {count} business-card image(s) past the {settings.business_card_retention_days}-day retention period.")


if __name__ == "__main__":
    main()
