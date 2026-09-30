"""Reconcile indexes and assignment constraints on upgraded MVP databases."""
from alembic import op
import sqlalchemy as sa

revision = "0003_reconcile_current_schema"
down_revision = "0002_business_card_back_image"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "events" in tables:
        columns = {column["name"]: column for column in inspector.get_columns("events")}
        nullable = [name for name in ("created_at", "updated_at") if name in columns and columns[name]["nullable"]]
        if nullable:
            bind.execute(sa.text("UPDATE events SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
            bind.execute(sa.text("UPDATE events SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"))
            with op.batch_alter_table("events") as batch:
                for name in nullable:
                    batch.alter_column(name, existing_type=columns[name]["type"], nullable=False)

    if "interactions" not in tables:
        return

    columns = {column["name"]: column for column in inspector.get_columns("interactions")}
    if "updated_at" in columns and columns["updated_at"]["nullable"]:
        bind.execute(sa.text("UPDATE interactions SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"))
        with op.batch_alter_table("interactions") as batch:
            batch.alter_column("updated_at", existing_type=columns["updated_at"]["type"], nullable=False)

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("interactions")}
    for name, column in (
        ("ix_interactions_assigned_to", "assigned_to"),
        ("ix_interactions_created_at", "created_at"),
        ("ix_interactions_event_id", "event_id"),
        ("ix_interactions_status", "status"),
    ):
        if name not in indexes:
            op.create_index(name, "interactions", [column])

    foreign_keys = sa.inspect(bind).get_foreign_keys("interactions")
    if not any(item.get("constrained_columns") == ["assigned_to"] for item in foreign_keys):
        with op.batch_alter_table("interactions") as batch:
            batch.create_foreign_key(
                "fk_interactions_assigned_to_users", "users", ["assigned_to"], ["id"], ondelete="SET NULL"
            )


def downgrade() -> None:
    raise RuntimeError("Schema reconciliation is intentionally irreversible to avoid losing existing lead data.")
