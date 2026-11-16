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
    venue: Mapped[str | None] = mapped_column(String(180), nullable=True)
    profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("event_profiles.id", ondelete="SET NULL"), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    next_lead_number: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    interactions: Mapped[list["Interaction"]] = relationship(back_populates="event")


class EventProfile(Base):
    __tablename__ = "event_profiles"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    venue: Mapped[str | None] = mapped_column(String(180), nullable=True)
    location: Mapped[str | None] = mapped_column(String(180), nullable=True)
    sessions_template: Mapped[list[dict]] = mapped_column(JSON, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class EventSession(Base):
    __tablename__ = "event_sessions"
    __table_args__ = (UniqueConstraint("event_id", "slug", name="uq_event_sessions_event_slug"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    slug: Mapped[str] = mapped_column(String(120))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    venue: Mapped[str | None] = mapped_column(String(180), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class EventStaff(Base):
    __tablename__ = "event_staff"
    __table_args__ = (UniqueConstraint("event_id", "user_id", name="uq_event_staff_event_user"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(40), default="staff")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


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
    full_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    company: Mapped[str | None] = mapped_column(String(180), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(180), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_type: Mapped[str] = mapped_column(String(20), default="work")
    normalized_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    normalized_phone: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
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
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("event_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    captured_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
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
    synthetic_test: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    exclude_from_analytics: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
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


class StaffCardCapture(Base):
    __tablename__ = "staff_card_captures"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("event_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    captured_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True)
    interaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("interactions.id", ondelete="SET NULL"), nullable=True, index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(80))
    file_size: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(1000))
    ocr_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="pending_review", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    synthetic_test: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    exclude_from_analytics: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    external_ai_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_ai_consent_notice_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


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


class Meeting(Base):
    __tablename__ = "meetings"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"), nullable=True, index=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    interaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("interactions.id", ondelete="SET NULL"), nullable=True, index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    topics: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    demo_presented: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="confirmed", index=True)
    next_steps: Mapped[str] = mapped_column(Text, default="")
    follow_up_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class ResearchImportBatch(Base):
    __tablename__ = "research_import_batches"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(30), default="preview", index=True)
    sheet_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[dict]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ResearchImportRow(Base):
    __tablename__ = "research_import_rows"
    __table_args__ = (UniqueConstraint("batch_id", "sheet_name", "source_row", name="uq_research_import_batch_sheet_row"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_import_batches.id", ondelete="CASCADE"), index=True)
    sheet_name: Mapped[str] = mapped_column(String(255))
    source_row: Mapped[int] = mapped_column(Integer)
    source_key: Mapped[str] = mapped_column(String(500))
    profile_id: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    row_data: Mapped[dict] = mapped_column(JSON)
    validation_errors: Mapped[list[str]] = mapped_column(JSON, default=list)
    previous_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class EventRegistrant(Base):
    __tablename__ = "event_registrants"
    __table_args__ = (UniqueConstraint("event_id", "source_key", name="uq_event_registrants_event_source"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    last_import_batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("research_import_batches.id", ondelete="SET NULL"), nullable=True, index=True)
    profile_id: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    source_key: Mapped[str] = mapped_column(String(500))
    source_filename: Mapped[str] = mapped_column(String(255))
    sheet_name: Mapped[str] = mapped_column(String(255))
    source_row: Mapped[int] = mapped_column(Integer)
    full_name: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    company: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    job_title: Mapped[str | None] = mapped_column(String(180), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    shortlist_status: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    cse_status: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    raw_data: Mapped[dict] = mapped_column(JSON)
    match_status: Mapped[str] = mapped_column(String(30), default="unmatched", index=True)
    reconciliation_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reconciliation_errors: Mapped[list[str]] = mapped_column(JSON, default=list)
    matched_lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


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
