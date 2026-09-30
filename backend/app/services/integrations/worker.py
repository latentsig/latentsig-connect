import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models import IntegrationJob, Interaction
from app.db.session import SessionLocal


def _sync_interaction(db, interaction: Interaction) -> None:
    from app.services.integrations.google_sheets import sync_interaction

    sync_interaction(db, interaction)


def process_one() -> bool:
    with SessionLocal() as db:
        job = db.scalar(
            select(IntegrationJob)
            .where(IntegrationJob.status == "pending")
            .where((IntegrationJob.next_retry_at.is_(None)) | (IntegrationJob.next_retry_at <= datetime.now(timezone.utc)))
            .order_by(IntegrationJob.created_at)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return False
        job.status = "processing"
        job.attempt_count += 1
        db.commit()
        job_id, job_type, entity_id, attempts = job.id, job.type, job.entity_id, job.attempt_count
    try:
        with SessionLocal() as db:
            if job_type == "google_sheets_upsert":
                interaction = db.get(Interaction, entity_id)
                if interaction is None:
                    raise ValueError("Interaction no longer exists")
                _sync_interaction(db, interaction)
            else:
                raise ValueError(f"Unknown integration job type: {job_type}")
        with SessionLocal() as db:
            job = db.get(IntegrationJob, job_id)
            job.status, job.last_error, job.next_retry_at = "succeeded", None, None
            db.commit()
    except Exception as exc:
        delay = min(3600, 30 * (2 ** min(attempts - 1, 7)))
        with SessionLocal() as db:
            job = db.get(IntegrationJob, job_id)
            job.status = "failed" if attempts >= 10 else "pending"
            job.last_error = str(exc)[:2000]
            job.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            db.commit()
    return True


def main() -> None:
    print("LatentSig integration worker started")
    while True:
        if not process_one():
            time.sleep(2)


if __name__ == "__main__":
    main()
