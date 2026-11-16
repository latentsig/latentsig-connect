"""Add event-scoped encounters for research attendees without leads."""
from alembic import op
import sqlalchemy as sa


revision = "0010_event_encounters"
down_revision = "0009_event_research_meetings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "event_encounters" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "event_encounters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("registrant_id", sa.Uuid(), nullable=True),
        sa.Column("identity_key", sa.String(length=700), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("encounter_type", sa.String(length=30), nullable=False),
        sa.Column("encountered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("topics", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("demo_presented", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("next_steps", sa.Text(), nullable=False),
        sa.Column("follow_up_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synthetic_test", sa.Boolean(), nullable=False),
        sa.Column("exclude_from_analytics", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["employee_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["registrant_id"], ["event_registrants.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["event_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "event_id", "registrant_id", "identity_key", "lead_id", "session_id",
        "employee_id", "encounter_type", "encountered_at", "status", "follow_up_due_at",
    ):
        op.create_index(f"ix_event_encounters_{column}", "event_encounters", [column])
    op.create_index(
        "ix_event_encounters_event_identity", "event_encounters", ["event_id", "identity_key"]
    )


def downgrade() -> None:
    if "event_encounters" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("event_encounters")
