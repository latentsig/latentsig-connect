"""Add event workspaces, workbook research, meetings, and staff card capture."""
from alembic import op
import sqlalchemy as sa


revision = "0009_event_research_meetings"
down_revision = "0008_interaction_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    expected_tables = {
        "event_profiles", "event_sessions", "event_staff", "staff_card_captures",
        "meetings", "research_import_batches", "research_import_rows", "event_registrants",
    }
    required_columns = {
        "events": {"venue", "profile_id"},
        "interactions": {"session_id", "captured_by_user_id", "synthetic_test", "exclude_from_analytics"},
    }
    schema_ready = expected_tables.issubset(tables) and all(
        columns.issubset({item["name"] for item in inspector.get_columns(table)})
        for table, columns in required_columns.items()
    )
    # The original baseline migration uses Base.metadata.create_all(). On a fresh
    # database that creates the current model schema, so skip duplicate DDL here.
    if schema_ready:
        op.execute("UPDATE events SET start_date='2026-11-17', end_date='2026-11-19', location=COALESCE(location, 'Bengaluru') WHERE slug='bts-2026'")
        return

    op.create_table(
        "event_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("venue", sa.String(length=180), nullable=True),
        sa.Column("location", sa.String(length=180), nullable=True),
        sa.Column("sessions_template", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_profiles_name", "event_profiles", ["name"], unique=True)
    with op.batch_alter_table("events") as batch:
        batch.add_column(sa.Column("venue", sa.String(length=180), nullable=True))
        batch.add_column(sa.Column("profile_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_events_profile_id_event_profiles", "event_profiles", ["profile_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_events_profile_id", ["profile_id"])
    op.create_table(
        "event_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("venue", sa.String(length=180), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "slug", name="uq_event_sessions_event_slug"),
    )
    op.create_index("ix_event_sessions_event_id", "event_sessions", ["event_id"])
    op.create_table(
        "event_staff",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "user_id", name="uq_event_staff_event_user"),
    )
    op.create_index("ix_event_staff_event_id", "event_staff", ["event_id"])
    op.create_index("ix_event_staff_user_id", "event_staff", ["user_id"])
    with op.batch_alter_table("interactions") as batch:
        batch.add_column(sa.Column("session_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("captured_by_user_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("synthetic_test", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("exclude_from_analytics", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_foreign_key("fk_interactions_session_id_event_sessions", "event_sessions", ["session_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_interactions_captured_by_user_id_users", "users", ["captured_by_user_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_interactions_session_id", ["session_id"])
        batch.create_index("ix_interactions_captured_by_user_id", ["captured_by_user_id"])
    with op.batch_alter_table("leads") as batch:
        for name, length in (("full_name", 180), ("company", 180), ("job_title", 180), ("email", 320), ("normalized_email", 320), ("phone", 40), ("normalized_phone", 40)):
            batch.alter_column(name, existing_type=sa.String(length=length), nullable=True)
    op.create_table(
        "staff_card_captures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("captured_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("interaction_id", sa.Uuid(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=80), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(length=1000), nullable=False),
        sa.Column("ocr_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("synthetic_test", sa.Boolean(), nullable=False),
        sa.Column("exclude_from_analytics", sa.Boolean(), nullable=False),
        sa.Column("external_ai_consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_ai_consent_notice_version", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["captured_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["event_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["interaction_id"], ["interactions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("event_id", "session_id", "captured_by_user_id", "lead_id", "interaction_id", "status"):
        op.create_index(f"ix_staff_card_captures_{column}", "staff_card_captures", [column])
    op.create_table(
        "meetings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("interaction_id", sa.Uuid(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("topics", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("demo_presented", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("next_steps", sa.Text(), nullable=False),
        sa.Column("follow_up_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["employee_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["interaction_id"], ["interactions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("event_id", "lead_id", "interaction_id", "employee_id", "status", "follow_up_due_at"):
        op.create_index(f"ix_meetings_{column}", "meetings", [column])
    op.create_table(
        "research_import_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("sheet_names", sa.JSON(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("event_id", "uploaded_by", "file_sha256", "status"):
        op.create_index(f"ix_research_import_batches_{column}", "research_import_batches", [column])
    op.create_table(
        "research_import_rows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("sheet_name", sa.String(length=255), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(length=500), nullable=False),
        sa.Column("profile_id", sa.String(length=180), nullable=True),
        sa.Column("row_data", sa.JSON(), nullable=False),
        sa.Column("validation_errors", sa.JSON(), nullable=False),
        sa.Column("previous_data", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["research_import_batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "sheet_name", "source_row", name="uq_research_import_batch_sheet_row"),
    )
    op.create_index("ix_research_import_rows_batch_id", "research_import_rows", ["batch_id"])
    op.create_index("ix_research_import_rows_profile_id", "research_import_rows", ["profile_id"])
    op.create_table(
        "event_registrants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("last_import_batch_id", sa.Uuid(), nullable=True),
        sa.Column("profile_id", sa.String(length=180), nullable=True),
        sa.Column("source_key", sa.String(length=500), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("sheet_name", sa.String(length=255), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=180), nullable=True),
        sa.Column("company", sa.String(length=180), nullable=True),
        sa.Column("job_title", sa.String(length=180), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=80), nullable=True),
        sa.Column("shortlist_status", sa.String(length=80), nullable=True),
        sa.Column("cse_status", sa.String(length=80), nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=False),
        sa.Column("match_status", sa.String(length=30), nullable=False),
        sa.Column("reconciliation_required", sa.Boolean(), nullable=False),
        sa.Column("reconciliation_errors", sa.JSON(), nullable=False),
        sa.Column("matched_lead_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["last_import_batch_id"], ["research_import_batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["matched_lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "source_key", name="uq_event_registrants_event_source"),
    )
    for column in ("event_id", "last_import_batch_id", "profile_id", "full_name", "company", "shortlist_status", "cse_status", "match_status", "matched_lead_id"):
        op.create_index(f"ix_event_registrants_{column}", "event_registrants", [column])
    op.execute("UPDATE events SET start_date='2026-11-17', end_date='2026-11-19', location=COALESCE(location, 'Bengaluru') WHERE slug='bts-2026'")


def downgrade() -> None:
    for name in ("event_registrants", "research_import_rows", "research_import_batches", "meetings", "staff_card_captures"):
        op.drop_table(name)
    with op.batch_alter_table("leads") as batch:
        for name, length in (("full_name", 180), ("company", 180), ("job_title", 180), ("email", 320), ("normalized_email", 320), ("phone", 40), ("normalized_phone", 40)):
            batch.alter_column(name, existing_type=sa.String(length=length), nullable=False)
    with op.batch_alter_table("interactions") as batch:
        batch.drop_index("ix_interactions_captured_by_user_id")
        batch.drop_index("ix_interactions_session_id")
        batch.drop_constraint("fk_interactions_captured_by_user_id_users", type_="foreignkey")
        batch.drop_constraint("fk_interactions_session_id_event_sessions", type_="foreignkey")
        batch.drop_column("exclude_from_analytics")
        batch.drop_column("synthetic_test")
        batch.drop_column("captured_by_user_id")
        batch.drop_column("session_id")
    op.drop_table("event_staff")
    op.drop_table("event_sessions")
    with op.batch_alter_table("events") as batch:
        batch.drop_index("ix_events_profile_id")
        batch.drop_constraint("fk_events_profile_id_event_profiles", type_="foreignkey")
        batch.drop_column("profile_id")
        batch.drop_column("venue")
    op.drop_index("ix_event_profiles_name", table_name="event_profiles")
    op.drop_table("event_profiles")
