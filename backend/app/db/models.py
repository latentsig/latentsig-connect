import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(180))
    role: Mapped[str] = mapped_column(String(20), default="SALES")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(180))
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    location: Mapped[str | None] = mapped_column(String(180), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    next_lead_number: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    interactions: Mapped[list["Interaction"]] = relationship(back_populates="event")


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("normalized_email", name="uq_leads_normalized_email"),
        UniqueConstraint("normalized_phone", name="uq_leads_normalized_phone"),
        Index("ix_leads_company", "company"),
        Index("ix_leads_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lead_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(180))
    company: Mapped[str] = mapped_column(String(180))
    job_title: Mapped[str] = mapped_column(String(180))
    email: Mapped[str] = mapped_column(String(320))
    email_type: Mapped[str] = mapped_column(String(20), default="work")
    normalized_email: Mapped[str] = mapped_column(String(320))
    phone: Mapped[str] = mapped_column(String(40))
    normalized_phone: Mapped[str] = mapped_column(String(40), index=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    interactions: Mapped[list["Interaction"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    notes: Mapped[list["LeadNote"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    business_cards: Mapped[list["BusinessCard"]] = relationship(back_populates="lead", cascade="all, delete-orphan")


class Interaction(Base):
    __tablename__ = "interactions"
    __table_args__ = (
        Index("ix_interactions_created_at", "created_at"), Index("ix_interactions_status", "status"),
        Index("ix_interactions_idempotency_key", "idempotency_key", unique=True),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("events.id"), nullable=True, index=True)
    interest: Mapped[list[str]] = mapped_column(JSON)
    intent: Mapped[str] = mapped_column(String(180))
    other_interest_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    other_intent_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirement_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_processing_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    follow_up_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_notice_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ai_processing_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ai_processing_consent_notice_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(36), nullable=True)
    submission_created: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    capture_method: Mapped[str] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(String(180), default="direct")
    captured_by: Mapped[str | None] = mapped_column(String(180), nullable=True)
    utm_source: Mapped[str | None] = mapped_column(String(180), nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(String(180), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(180), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="new")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    lead: Mapped[Lead] = relationship(back_populates="interactions")
    event: Mapped[Event | None] = relationship(back_populates="interactions")
    business_card: Mapped["BusinessCard | None"] = relationship(back_populates="interaction", uselist=False)
    notes: Mapped[list["LeadNote"]] = relationship(back_populates="interaction")


class BusinessCard(Base):
    __tablename__ = "business_cards"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    interaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("interactions.id", ondelete="CASCADE"), unique=True)
    storage_path: Mapped[str] = mapped_column(String(1000))
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(80))
    file_size: Mapped[int] = mapped_column(Integer)
    ocr_text: Mapped[str] = mapped_column(Text, default="")
    ocr_json: Mapped[dict] = mapped_column(JSON, default=dict)
    back_storage_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    back_original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    back_mime_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    back_file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    lead: Mapped[Lead] = relationship(back_populates="business_cards")
    interaction: Mapped[Interaction] = relationship(back_populates="business_card")


class LeadNote(Base):
    __tablename__ = "lead_notes"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    interaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("interactions.id", ondelete="SET NULL"), nullable=True)
    author_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    lead: Mapped[Lead] = relationship(back_populates="notes")
    interaction: Mapped[Interaction | None] = relationship(back_populates="notes")
    author: Mapped[User] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(80))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    user: Mapped[User | None] = relationship()


class IntegrationJob(Base):
    __tablename__ = "integration_jobs"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
